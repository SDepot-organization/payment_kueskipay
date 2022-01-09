# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import odoo.tests

from datetime import datetime
from odoo import fields
from odoo.addons.payment.tests.common import PaymentAcquirerCommon
from odoo.tests.common import users


class SepaDirectDebitCommon(PaymentAcquirerCommon):

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.accountman = cls.env.user
        cls.company = cls.env.company
        cls.company.sdd_creditor_identifier = 'BE30ZZZ300D000000042'
        cls.EUR = cls.env.ref('base.EUR').id
        bank_ing = cls.env['res.bank'].create({'name': 'ING', 'bic': 'BBRUBEBB'})
        
        cls.sepa_bank_account = cls.env['res.partner.bank'].create({
            'acc_number': 'NL91 ABNA 0417 1643 00',
            'partner_id': cls.company.partner_id.id,
            'bank_id': bank_ing.id,
        })

        assert cls.sepa_bank_account.acc_type == 'iban'

        cls.sepa_journal = cls.company_data['default_journal_bank']
        cls.sepa_journal.bank_account_id = cls.sepa_bank_account

        cls.sepa = cls.env.ref('payment.payment_acquirer_sepa_direct_debit')
        cls.sepa.write({
            'company_id': cls.env.company.id,
            'journal_id': cls.sepa_journal.id,
            'state': 'enabled',
            'sepa_direct_debit_sms_enabled': True,
        })

        # create the partner bank account
        partner_bank = cls.env['res.partner.bank'].create({
            'acc_number': 'BE17412614919710',
            'partner_id': cls.buyer_id,
            'company_id': cls.company.id,
        })

        cls.mandate = cls.env['sdd.mandate'].create({
            'partner_id': cls.buyer_id,
            'company_id': cls.company.id,
            'partner_bank_id': partner_bank.id,
            'start_date': fields.date.today(),
            'payment_journal_id': cls.sepa_journal.id,
            'verified': True,
            'state': 'active',
        })

    def reconcile(self, payment):
        bank_journal = payment.journal_id
        move_line = payment.line_ids.filtered(lambda aml: aml.account_id == bank_journal.payment_debit_account_id)

        bank_stmt = self.env['account.bank.statement'].with_user(self.accountman).create({
            'journal_id': bank_journal.id,
            'date': payment.date,
            'name': payment.name,
            'line_ids': [(0, 0, {
                'partner_id': self.buyer_id,
                'foreign_currency_id': move_line.currency_id.id,
                'amount_currency': abs(move_line.amount_currency),
                'amount': abs(move_line.balance),
                'date': payment.date,
                'payment_ref': payment.name,
            })],
        })
        bank_stmt.button_post()
        bank_stmt.line_ids.reconcile([{'id': move_line.id}])

        self.assertTrue(payment.is_matched, 'payment should be reconciled')


@odoo.tests.tagged('post_install', '-at_install')
class TestSepaDirectDebit(SepaDirectDebitCommon):

    @users('accountman','demo')
    def test_sepa_direct_debit_s2s_process(self):
        payment_token = self.env['payment.token'].with_user(self.accountman).create({
            'acquirer_id': self.sepa.id,
            'partner_id': self.buyer_id,
            'sdd_mandate_id': self.mandate.id,
            'acquirer_ref': self.mandate.name,
        })

        tx = self.env['payment.transaction'].with_user(self.accountman).create({
            'reference': 'test_ref_%s' % fields.datetime.now(),
            'currency_id': self.EUR,
            'partner_id': self.buyer_id,
            'amount': 10.0,
            'acquirer_id': self.sepa.id,
            'payment_token_id': payment_token.id,
            'type': 'server2server',
            'date': datetime.now(),
        })

        # 1. capture transaction
        tx.sepa_direct_debit_s2s_do_transaction()

        self.assertEqual(tx.payment_token_id.verified, True)
        self.assertEqual(tx.state, 'pending', 'payment transaction should be pending')
        self.assertEqual(tx.payment_id.state, 'posted', 'account payment should be posted')
        self.assertEqual(tx.payment_id.sdd_mandate_id.id, self.mandate.id)

        # 2. reconcile
        self.reconcile(tx.payment_id)

        self.assertEqual(tx.state, 'done', 'payment transaction should be done')
