# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.tools.float_utils import float_compare
from odoo.tools import float_round
from odoo.addons.payment.models.payment_acquirer import _partner_format_address, _partner_split_name

import logging
import pprint

_logger = logging.getLogger(__name__)


class KueskiPayPaymentAcquirer(models.Model):
	_inherit = 'payment.acquirer'

	provider = fields.Selection(selection_add=[
		('kueskipay', 'KueskiPay Payment')
	], default='kueskipay', ondelete={'kueskipay': 'set default'})

	ksk_websitekey = fields.Char(
		string='ksk_websitekey',
		required_if_provider='kueskipay',
		groups='base.group_user',
	)
	ksk_secretkey = fields.Char(
		string='ksk_secretkey',
		required_if_provider='kueskipay',
		groups='base.group_user',
	)

	@api.model
	def _create_missing_journal_for_acquirers(self, company=None):
		# By default, the kueskipay method uses the default Bank journal.
		company = company or self.env.company
		acquirers = self.env['payment.acquirer'].search(
			[('provider', '=', 'kueskipay'), ('journal_id', '=', False), ('company_id', '=', company.id)])

		bank_journal = self.env['account.journal'].search(
			[('type', '=', 'bank'), ('company_id', '=', company.id)], limit=1)
		if bank_journal:
			acquirers.write({'journal_id': bank_journal.id})
		return super(KueskiPayPaymentAcquirer, self)._create_missing_journal_for_acquirers(company=company)

	def get_form_action_url(self, tx_values):
		""" Returns the form action URL, for form-based acquirer implementations. """
		custom_method_name = '%s_get_form_action_url' % self.provider
		callback_url = self.env['ir.config_parameter'].sudo().get_param('payment.callback_url', '0')#custom
		if not hasattr(self, custom_method_name):
			return False
		elif callback_url != '0':
			return callback_url
		elif self.provider == 'kueskipay':
			return getattr(self, custom_method_name)(tx_values)
		else:
			return getattr(self, custom_method_name)()


	#override
	def render(self, reference, amount, currency_id, partner_id=False, values=None):
		""" Renders the form template of the given acquirer as a qWeb template.
		:param string reference: the transaction reference
		:param float amount: the amount the buyer has to pay
		:param currency_id: currency id
		:param dict partner_id: optional partner_id to fill values
		:param dict values: a dictionary of values for the transction that is
		given to the acquirer-specific method generating the form values

		All templates will receive:

		 - acquirer: the payment.acquirer browse record
		 - user: the current user browse record
		 - currency_id: id of the transaction currency
		 - amount: amount of the transaction
		 - reference: reference of the transaction
		 - partner_*: partner-related values
		 - partner: optional partner browse record
		 - 'feedback_url': feedback URL, controler that manage answer of the acquirer (without base url) -> FIXME
		 - 'return_url': URL for coming back after payment validation (wihout base url) -> FIXME
		 - 'cancel_url': URL if the client cancels the payment -> FIXME
		 - 'error_url': URL if there is an issue with the payment -> FIXME
		 - context: Odoo context

		"""
		if values is None:
			values = {}

		if not self.view_template_id:
			return None

		values.setdefault('return_url', '/payment/process')
		# reference and amount
		values.setdefault('reference', reference)
		amount = float_round(amount, 2)
		values.setdefault('amount', amount)

		# currency id
		currency_id = values.setdefault('currency_id', currency_id)
		if currency_id:
			currency = self.env['res.currency'].browse(currency_id)
		else:
			currency = self.env.company.currency_id
		values['currency'] = currency

		# Fill partner_* using values['partner_id'] or partner_id argument
		partner_id = values.get('partner_id', partner_id)
		billing_partner_id = values.get('billing_partner_id', partner_id)
		if partner_id:
			partner = self.env['res.partner'].browse(partner_id)
			if partner_id != billing_partner_id:
				billing_partner = self.env['res.partner'].browse(billing_partner_id)
			else:
				billing_partner = partner
			values.update({
				'partner': partner,
				'partner_id': partner_id,
				'partner_name': partner.name,
				'partner_lang': partner.lang,
				'partner_email': partner.email,
				'partner_zip': partner.zip,
				'partner_city': partner.city,
				'partner_address': _partner_format_address(partner.street, partner.street2),
				'partner_country_id': partner.country_id.id or self.env.company.country_id.id,
				'partner_country': partner.country_id,
				'partner_phone': partner.phone,
				'partner_state': partner.state_id,
				'billing_partner': billing_partner,
				'billing_partner_id': billing_partner_id,
				'billing_partner_name': billing_partner.name,
				'billing_partner_commercial_company_name': billing_partner.commercial_company_name,
				'billing_partner_lang': billing_partner.lang,
				'billing_partner_email': billing_partner.email,
				'billing_partner_zip': billing_partner.zip,
				'billing_partner_city': billing_partner.city,
				'billing_partner_address': _partner_format_address(billing_partner.street, billing_partner.street2),
				'billing_partner_country_id': billing_partner.country_id.id,
				'billing_partner_country': billing_partner.country_id,
				'billing_partner_phone': billing_partner.phone,
				'billing_partner_state': billing_partner.state_id,
			})
		if values.get('partner_name'):
			values.update({
				'partner_first_name': _partner_split_name(values.get('partner_name'))[0],
				'partner_last_name': _partner_split_name(values.get('partner_name'))[1],
			})
		if values.get('billing_partner_name'):
			values.update({
				'billing_partner_first_name': _partner_split_name(values.get('billing_partner_name'))[0],
				'billing_partner_last_name': _partner_split_name(values.get('billing_partner_name'))[1],
			})

		# Fix address, country fields
		if not values.get('partner_address'):
			values['address'] = _partner_format_address(values.get('partner_street', ''), values.get('partner_street2', ''))
		if not values.get('partner_country') and values.get('partner_country_id'):
			values['country'] = self.env['res.country'].browse(values.get('partner_country_id'))
		if not values.get('billing_partner_address'):
			values['billing_address'] = _partner_format_address(values.get('billing_partner_street', ''), values.get('billing_partner_street2', ''))
		if not values.get('billing_partner_country') and values.get('billing_partner_country_id'):
			values['billing_country'] = self.env['res.country'].browse(values.get('billing_partner_country_id'))

		# compute fees
		fees_method_name = '%s_compute_fees' % self.provider
		if hasattr(self, fees_method_name):
			fees = getattr(self, fees_method_name)(values['amount'], values['currency_id'], values.get('partner_country_id'))
			values['fees'] = float_round(fees, 2)

		# call <name>_form_generate_values to update the tx dict with acqurier specific values
		cust_method_name = '%s_form_generate_values' % (self.provider)
		if hasattr(self, cust_method_name):
			method = getattr(self, cust_method_name)
			values = method(values)

		payment_status = self.env['ir.config_parameter'].sudo().get_param('payment.status', '0')#custom
		if payment_status != '0':
			values['payment_status'] = payment_status

		values.update({
			'tx_url': self._context.get('tx_url', self.get_form_action_url(values)),#custom
			'submit_class': self._context.get('submit_class', 'btn btn-link'),
			'submit_txt': self._context.get('submit_txt'),
			'acquirer': self,
			'user': self.env.user,
			'context': self._context,
			'type': values.get('type') or 'form',
		})

		_logger.info('payment.acquirer.render: <%s> values rendered for form payment:\n%s', self.provider, pprint.pformat(values))
		return self.view_template_id._render(values, engine='ir.qweb')

	def kueskipay_get_form_action_url(self, tx_values):
		return tx_values.pop('callback_url','algun_path_error')

	def kueskipay_form_generate_values(self, tx_values):
		from requests.exceptions import HTTPError
		import requests
		import json
		self.ensure_one()
		if self.state == 'enabled':
			url = 'https://api.kueskipay.com/v1/payments'
		else:
			url = 'https://testing.kueskipay.com/v1/payments'

		data = {
			"order_id": tx_values['reference'],#required,
			"description": tx_values['reference'],#"This is an amazing purchase",#required,
			"amount": {#required,
				"total": tx_values['amount'],#required,
				"currency": tx_values['currency'].name,#required,
				#"details": {
				#	"subtotal": values['???'],#required,
				#	"shipping": values['???'],
				#	"tax": values['???'],
				#},
			},
			#"items": [
			#	{
			#		"name": values['???'],#"Amazing Article",#required,
			#		"description": values['???'],#"This is an amazing article",
			#		"quantity": values['???'],#required,
			#		"price": values['???'],#required,
			#		"currency": values['???'],#"MXN",#required,
			#		"sku": values['???'],#"001",
			#	},
			#],
			"shipping": {
				"name": {#required,
					"name": tx_values['partner_first_name'],
					"last": tx_values['partner_last_name'],#required,
				},
				"address": {#required,
					"address": tx_values['partner_address'],#required,
					#"interior": values['???'],#"Piso 03-15",
					#"neighborhood": values['???'],#"Circunvalación Américas",
					"city": tx_values['partner_city'],#required,
					"state": tx_values['partner_state'].name,#required,
					"zipcode": tx_values['partner_zip'],#required,
					"country": tx_values['partner_country'].name,#required,
				},
				"phone_number": tx_values['partner_phone'],
				"email": tx_values['partner_email'],
			},
			"billing": {
				"business": {
					"name": tx_values['billing_partner_commercial_company_name'] or tx_values['billing_partner_name'],#required,
					#"rfc": values['???'],#"DODJ210610HM4",
				},
				"address": {
					"address": tx_values['billing_partner_address'],#"Varsovia 36",#required,
					#"neighborhood": values['???'],#"Juárez",
					"city": tx_values['billing_partner_city'],#required,
					"state": tx_values['billing_partner_state'].name,#required,
					"zipcode": tx_values['billing_partner_zip'],#required,
					"country": tx_values['billing_partner_country'].name#required,
				},
				"phone_number": tx_values['billing_partner_phone'],
				"email": tx_values['billing_partner_email'],
			},
			"callbacks": {
				#"on_success": urls.url_join(base_url, '/payment/transfer/feedback'),
				#"on_reject": urls.url_join(base_url, TransferController._reject_url),
				#"on_canceled": urls.url_join(base_url, TransferController._cancel_url),
				#"on_failed": urls.url_join(base_url, TransferController._exception_url),
			},
		}

		headers = {
		  'Authorization': 'Bearer %s' % self.sudo().ksk_websitekey,
		  'Content-Type': 'application/json'
		}

		resp = requests.request("POST", url, headers=headers, data=data)
		if False:#if not resp.ok or (400 <= resp.status_code < 500 or resp.json().get('code')):
			try:
				resp.raise_for_status()
			except HTTPError:
				_logger.error(resp.text)
				error = resp.json().get('message', '')
				error_msg = " " + (_("KueskiPay gave us the following info about the problem: '%s'", error))
				raise ValidationError(error_msg)
		tx_values['callback_url'] = 'https://testing.kueskipay.com/pay?payment_id=410087042715935'#tx_values['callback_url'] = resp.json().get('data').get('callback_url')
		return tx_values

	def _format_kueskipay_data(self):
		company_id = self.env.company.id
		# filter only bank accounts marked as visible
		journals = self.env['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', company_id)])
		accounts = journals.mapped('bank_account_id').name_get()
		bank_title = _('Bank Accounts') if len(accounts) > 1 else _('Bank Account')
		bank_accounts = ''.join(['<ul>'] + ['<li>%s</li>' % name for id, name in accounts] + ['</ul>'])
		post_msg = _('''<div>
<h3>Please use the following kueskipay details</h3>
<h4>%(bank_title)s</h4>
%(bank_accounts)s
<h4>Communication</h4>
<p>Please use the order name as communication reference.</p>
</div>''') % {
			'bank_title': bank_title,
			'bank_accounts': bank_accounts,
		}
		return post_msg

	@api.model
	def create(self, values):
		""" Hook in create to create a default pending_msg. This is done in create
		to have access to the name and other creation values. If no pending_msg
		or a void pending_msg is given at creation, generate a default one. """
		if values.get('provider') == 'kueskipay' and not values.get('pending_msg'):
			values['pending_msg'] = self._format_kueskipay_data()
		return super(KueskiPayPaymentAcquirer, self).create(values)

	def write(self, values):
		""" Hook in write to create a default pending_msg. See create(). """
		if not values.get('pending_msg', False) and all(not acquirer.pending_msg and acquirer.provider != 'kueskipay' for acquirer in self) and values.get('provider') == 'kueskipay':
			values['pending_msg'] = self._format_kueskipay_data()
		return super(KueskiPayPaymentAcquirer, self).write(values)


class KueskiPayPaymentTransaction(models.Model):
	_inherit = 'payment.transaction'

	@api.model
	def _kueskipay_form_get_tx_from_data(self, data):
		reference, amount, currency_name = data.get('reference'), data.get('amount'), data.get('currency_name')
		transaction = self.search([('reference', '=', reference)])

		if not transaction or len(transaction) > 1:
			error_msg = _('received data for reference %s') % (pprint.pformat(reference))
			if not transaction:
				error_msg += _('; no order found')
			else:
				error_msg += _('; multiple order found')
			_logger.info(error_msg)
			raise ValidationError(error_msg)

		return transaction

	def _kueskipay_form_get_invalid_parameters(self, data):
		invalid_parameters = []

		if float_compare(float(data.get('amount') or '0.0'), self.amount, 2) != 0:
			invalid_parameters.append(('amount', data.get('amount'), '%.2f' % self.amount))
		if data.get('currency') != self.currency_id.name:
			invalid_parameters.append(('currency', data.get('currency'), self.currency_id.name))

		return invalid_parameters

	def _kueskipay_form_validate(self, data):
		_logger.info('Validated kueskipay payment for tx %s: set as pending' % (self.reference))
		state = data.get('state', 'draft')
		if state == 'draft':
			self.write({'acquirer_reference': data.get('reference')})
			#self._set_transaction_??????()
			return True
		elif state == 'pending':
			self.write({'acquirer_reference': data.get('reference')})
			self._set_transaction_pending()
			return True
		elif state == 'authorized':
			self.write({'acquirer_reference': data.get('reference')})
			self._set_transaction_authorized()
			return True
		elif state == 'done':
			self.write({'acquirer_reference': data.get('reference')})
			self._set_transaction_done()
			return True
		elif state == 'cancel':
			self.write({'acquirer_reference': data.get('reference')})
			self._set_transaction_cancel()
			return True
		#elif state == 'error':
		else:
			state_message = data.get('error', 'un mensaje de error'),
			self.write({
				'acquirer_reference': data.get('reference'),
				'state_message': state_message,
			})
			self._set_transaction_error(state_message)
			return False

