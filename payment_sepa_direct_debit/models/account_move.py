# -*- coding: utf-8 -*-
from odoo import models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def reconcile(self):
        # OVERRIDE
        # when a payment is renconciled, its transaction's status transitions from pending to done.
        # the post processing is called subsequently, it will confirm and invoice the sale order.
        res = super().reconcile()

        involved_payments = self.move_id.payment_id
        tx_ids = self.env['payment.transaction'].sudo().search([
            ('state', '=', 'pending'),
            ('acquirer_id.provider', '=', 'sepa_direct_debit'),
            ('payment_id', 'in', involved_payments.filtered('is_matched').ids),
        ]).ids
        txs = self.env['payment.transaction'].browse(tx_ids)
        txs._set_transaction_done()
        txs.execute_callback()
        txs._post_process_after_done()

        return res
