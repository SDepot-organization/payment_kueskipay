# -*- coding: utf-8 -*-
import logging

from datetime import datetime
from random import randint

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, AccessError
from odoo.addons.base.models.res_bank import sanitize_account_number
from odoo.addons.base_iban.models.res_partner_bank import validate_iban


_logger = logging.getLogger(__name__)


class PaymentAcquirerSepaDirectDebit(models.Model):
    _inherit = 'payment.acquirer'

    provider = fields.Selection(selection_add=[
        ('sepa_direct_debit', 'SEPA Direct Debit')
    ], ondelete={'sepa_direct_debit': 'set default'})
    sepa_direct_debit_sms_enabled = fields.Boolean('SMS Authentication', default=False, help='A verification code is sent by SMS to the customer.')
    sepa_direct_debit_sign_enabled = fields.Boolean('Online Signature', default=False, help='Ask your customer to include their signature during the payment process.')
    iap_sms_credits = fields.Monetary('SMS Credits', compute='_compute_iap_credits', store=False)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency', store=False, readonly=True)

    @api.constrains('country_ids')
    def _check_sepa_zone(self):
        sepa_zone = self.env.ref('base.sepa_zone').mapped('country_ids.code')
        for record in self:
            if record.provider != 'sepa_direct_debit':
                continue

            non_sepa_countries = [c.name for c in record.country_ids if c.code not in sepa_zone]
            if non_sepa_countries:
                raise ValidationError(_("Restricted to countries of the SEPA Zone. %s not allowed.") % ', '.join(non_sepa_countries))

    @api.depends('provider')
    def _compute_iap_credits(self):
        creds = self.env['iap.account'].get_credits('sms')
        self.filtered(lambda a: a.provider == 'sepa_direct_debit').update({'iap_sms_credits': creds})
        self.filtered(lambda a: a.provider != 'sepa_direct_debit').update({'iap_sms_credits': 0})

    def buy_credits(self):
        url = self.env['iap.account'].get_credits_url(base_url='', service_name='sms')
        return {
            'type': 'ir.actions.act_url',
            'url': url,
        }

    def _create_missing_journal_for_acquirers(self, company=None):
        company = company or self.env.company
        acquirers = self.env['payment.acquirer'].search([
            ('provider', '=', 'sepa_direct_debit'),
            ('journal_id', '=', False),
            ('company_id', '=', company.id)
        ])

        bank_journal = self.env['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', company.id)], limit=1)

        if bank_journal:
            acquirers.write({'journal_id': bank_journal.id})

        return super(PaymentAcquirerSepaDirectDebit, self)._create_missing_journal_for_acquirers(company=company)

    def _check_setup(self):
        for record in self.filtered(lambda acq: acq.provider == 'sepa_direct_debit' and acq.state == 'enabled'):
            if record.journal_id.bank_account_id.acc_type != 'iban':
                raise ValidationError(_('The bank account of the payment journal must be a valid IBAN.'))

            if not record.company_id.sdd_creditor_identifier:
                raise ValidationError(_("Your company must have a creditor identifier in order to issue SEPA Direct Debit payments requests. It can be defined in accounting module's settings."))

    def _get_feature_support(self):
        """Get advanced feature support by provider.

        Each provider should add its technical in the corresponding
        key for the following features:
            * tokenize: support saving payment data in a payment.tokenize
                        object
        """
        res = super(PaymentAcquirerSepaDirectDebit, self)._get_feature_support()
        res['tokenize'].append('sepa_direct_debit')
        return res

    def write(self, vals):
        result = super(PaymentAcquirerSepaDirectDebit, self).write(vals)
        self._check_setup()
        return result

    # --------------------------------------------------------------------------
    # S2S RELATED METHODS
    # --------------------------------------------------------------------------
    def sepa_direct_debit_s2s_form_validate(self, data):
        error = dict()

        mandatory_fields = ["iban", 'acquirer_id', 'partner_id']

        for field_name in mandatory_fields:
            if not data.get(field_name):
                error[field_name] = 'missing'

        return False if error else True

    def sepa_direct_debit_s2s_form_process(self, data):
        partner_id = int(data['partner_id'])
        if not data.get('mandate_id'):
            iban = sanitize_account_number(data['iban'])

            same_iban_acc = self.env['res.partner.bank'].search([
                ('sanitized_acc_number', '=', iban),
                ('company_id', '=', self.env.company.id)],limit=1)
            if same_iban_acc:
                raise ValidationError(_("This account is not available. Please log in to continue."))

            # will raise a ValidationError given an invalid format
            validate_iban(iban)

            mandate = self._create_or_find_mandate(iban, partner_id)
        else:
            partner = self.env['res.partner'].browse(partner_id).sudo()
            mandate = self.env['sdd.mandate'].browse(data['mandate_id'])
            # since we're in a sudoed env, we need to add a few checks
            if mandate.partner_id != partner.commercial_partner_id:
                raise AccessError(_('Identity mismatch'))
        iban_mask = 'X'*(len(data['iban'])-4) + data['iban'][-4:]
        payment_token = self.env['payment.token'].sudo().create({
            'sdd_mandate_id': mandate.id,
            'name': _('Direct Debit: ') + iban_mask,
            'acquirer_ref': mandate.name,
            'acquirer_id': int(data['acquirer_id']),
            'partner_id': partner_id,
        })
        return payment_token

    def _create_or_find_mandate(self, iban, partner_id):
        self.ensure_one()
        ResPartnerBank = self.env['res.partner.bank'].sudo()
        commercial_partner_id = self.env['res.partner'].browse(partner_id).sudo().commercial_partner_id.id

        partner_bank = ResPartnerBank.search([
            ('sanitized_acc_number', '=', sanitize_account_number(iban)),
            ('partner_id', 'child_of', commercial_partner_id)], limit=1)
        if not partner_bank:
            partner_bank = ResPartnerBank.create({
                'acc_number': iban,
                'partner_id': partner_id,
            })

        # avoid duplicate
        mandate = self.env['sdd.mandate'].sudo().search([
            ('state', 'not in', ['closed', 'revoked']),
            ('start_date', '<=', datetime.now()),
            '|', ('end_date', '>=', datetime.now()), ('end_date', '=', None),
            ('partner_id', '=', commercial_partner_id),
            ('partner_bank_id', '=', partner_bank.id),
            ('company_id', '=', self.env.company.id),
            '|', ('one_off', '=', False), ('payment_ids', '=', False)], limit=1)
        if not mandate:
            mandate = self.env['sdd.mandate'].sudo().create({
                'partner_id': commercial_partner_id,
                'partner_bank_id': partner_bank.id,
                'start_date': datetime.now(),
                'payment_journal_id': self.journal_id.id,
                'state': 'draft',
            })
        return mandate


class PaymentTxSepaDirectDebit(models.Model):
    _inherit = 'payment.transaction'

    # --------------------------------------------------------------------------
    # S2S RELATED METHODS
    # --------------------------------------------------------------------------
    def sepa_direct_debit_s2s_do_transaction(self, **kwargs):
        self.ensure_one()

        if self.state != 'draft':
            _logger.info('SEPA Direct Debit: trying to validate an already validated tx (ref %s)' % self.reference)
            return True

        if not self.payment_token_id or not self.payment_token_id.sdd_mandate_id:
            raise ValidationError(_('No SEPA Direct Debit mandate selected'))
        mandate = self.payment_token_id.sdd_mandate_id
        if not mandate:
            raise ValidationError(_('No SEPA Direct Debit mandate selected'))

        if mandate.partner_id != self.partner_id.commercial_partner_id:
            raise ValidationError(_('Mandate owner and customer do not match'))

        if not mandate.verified or not mandate.state == 'active' or (mandate.end_date and mandate.end_date > fields.Datetime.now()):
            raise ValidationError(_('Invalid mandate'))
        # the transaction should be pending as long as the account moves aren't reconciled.
        self._set_transaction_pending()
        self._notify_debit(mandate)

        # create associated account payment and make it a one2one with the transaction.
        payment = self._create_payment(add_payment_vals={
            'sdd_mandate_id': mandate.id,
            'payment_method_id': self.env.ref('account_sepa_direct_debit.payment_method_sdd').id,
        })

        vals = {
            'date': fields.datetime.now(),
            # 'acquirer_reference': '',  # TODO: what to put here
            'acquirer_id': self.acquirer_id.id,
            'partner_id': self.partner_id.id,
            'payment_id': payment.id,
        }

        self.write(vals)
        self.payment_token_id.verified = True

        return True

    def _notify_debit(self, mandate):
        """The SEPA Direct Debit rulebook requires that customers are notified each time a debit is to be made on their account.
        The notice must include:
            - The last 4 digits of the debtor’s bank account
            - The mandate reference
            - The amount to be debited
            - Your SEPA creditor identifier
            - Your contact information
        Notifications should be sent at least 14 calendar days before the payment is created unless specified otherwise.
        Odoo will send the notifications during transaction creation.
        """
        iban = mandate.partner_bank_id.acc_number.replace(' ', '')
        company = self.env.company

        template = self.env.ref('payment_sepa_direct_debit.mail_template_sepa_notify_debit')

        # only show the last 4 digits
        iban = ''.join(['*' for c in iban[:-4]]) + iban[-4:]

        ctx = self.env.context.copy()
        ctx.update({
            'iban': iban,
            'mandate_ref': mandate.name,
            'creditor_identifier': company.sdd_creditor_identifier,
        })

        template.with_context(ctx).send_mail(self.id)


class PaymentToken(models.Model):
    _inherit = 'payment.token'

    sdd_mandate_id = fields.Many2one('sdd.mandate', string='SEPA Direct Debit Mandate', readonly=True, ondelete="cascade")


class SDDMandate(models.Model):
    _inherit = 'sdd.mandate'

    phone_number = fields.Char('Phone Number',
                               help='Phone number used for authentication by code.',
                               copy=False,
                               readonly=True)
    verification_code = fields.Char('Verification Code', readonly=True, copy=False, groups='base.group_user')
    verified = fields.Boolean('Verified', default=False)
    signature = fields.Binary('Signature', help='Signature received through the portal.', copy=False, attachment=True, readonly=True)
    signed_by = fields.Char('Signed By', help='Name of the person that signed the mandate.', copy=False, readonly=True)
    signed_on = fields.Datetime('Signed On', help='Date of the signature.', copy=False, readonly=True)

    def _sign(self, signature=None, signer=None):
        self.ensure_one()
        vals = {
            'signed_on': fields.Datetime.now()
        }
        if signature:
            vals.update({
                'signature': signature,
                'signed_by': signer
            })
        self.write(vals)
        self.message_subscribe([self.partner_id.id])

    def _send_verification_code(self, phone):
        """ Sends a verification code to the given phone number. The code will
        be required to verify the ownership of the mandate.
        In Europe, it is required to register its identity with mobile operators.
        """
        self.ensure_one()
        if self.verified:
            raise ValidationError(_('This mandate has already been verified'))

        self.write({'phone_number': phone.replace(' ', ''), 'verification_code': randint(1000, 9999)})
        _logger.info('_send_verification_code: sending SMS to %s with code %s', self.phone_number, self.verification_code)
        if not self.env.registry.in_test_mode():
            self.env['sms.api'].sudo()._send_sms([self.phone_number], _('Your confirmation code is %s', self.verification_code))

    def _confirm(self, code=None, phone=None):
        """ Confirms the customer's ownership of the SEPA Direct Debit mandate.
        Confirmation succeeds if the verification codes match. Only the owner
        can confirm its mandates.
        """
        self.ensure_one()
        pt = self.env['payment.token'].sudo().search([
            ('acquirer_ref', '=', self.name),
        ], limit=1)
        if pt.acquirer_id.sepa_direct_debit_sms_enabled and not (code and phone):
            raise ValidationError(_("Phone number and/or verification code are required"))
        if pt.acquirer_id.sepa_direct_debit_sms_enabled and self.phone_number != phone:
            raise ValidationError(_('Phone number does not match'))
        if pt.acquirer_id.sepa_direct_debit_sms_enabled and self.verification_code != code:
            raise ValidationError(_('Verification code does not match'))
        template = self.env.ref('payment_sepa_direct_debit.mail_template_sepa_notify_validation')
        self.write({'state': 'active', 'verified': True})
        template.send_mail(self.id)

    def _update_mandate(self, code=None, phone=None, signer=None, signature=None):
        # This method will call _sign then _confirm and add a log in the chatter in case of an update
        # We need to call _sign first as it will add the current user as a follower
        self.ensure_one()
        self._sign(signature=signature, signer=signer)
        self._confirm(code=code, phone=phone)

        msg_list = []
        if (signature and signer):
            msg_list.append(_('The mandate was signed by %s') % signer)
        if (code and phone):
            msg_list.append(_('The mandate was validated with phone number %s') % phone)

        if msg_list:
            self._message_log(body='\n'.join(msg_list))

    def write(self, vals):
        res = super(SDDMandate, self).write(vals)
        if vals.get('state') in ['closed', 'revoked']:
            self.env['payment.token'].search([
                ('sdd_mandate_id', 'in', self.ids),
            ]).unlink()
        return res
