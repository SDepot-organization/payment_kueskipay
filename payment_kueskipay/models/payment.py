# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.tools.float_utils import float_compare

import logging
import pprint

_logger = logging.getLogger(__name__)


class KueskiPayPaymentAcquirer(models.Model):
	_inherit = 'payment.acquirer'

	provider = fields.Selection(selection_add=[
		('kueskipay', 'KueskiPay Payment')
	], default='kueskipay', ondelete={'kueskipay': 'set default'})

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

	def kueskipay_get_form_action_url(self):
		return '/payment/kueskipay/feedback'

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
		self._set_transaction_pending()
		return True