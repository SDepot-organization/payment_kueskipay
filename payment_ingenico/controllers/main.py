# -*- coding: utf-8 -*-
import logging
import pprint
import werkzeug
from werkzeug.urls import url_unquote_plus

from odoo import http
from odoo.http import request
from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.addons.payment.controllers.portal import PaymentProcessing

_logger = logging.getLogger(__name__)


class OgoneController(http.Controller):
	_accept_url = '/payment/ogone/test/accept'
	_decline_url = '/payment/ogone/test/decline'
	_exception_url = '/payment/ogone/test/exception'
	_cancel_url = '/payment/ogone/test/cancel'

	@http.route([
		'/payment/ogone/accept', '/payment/ogone/test/accept',
		'/payment/ogone/decline', '/payment/ogone/test/decline',
		'/payment/ogone/exception', '/payment/ogone/test/exception',
		'/payment/ogone/cancel', '/payment/ogone/test/cancel',
	], type='http', auth='public', csrf=False)
	def ogone_form_feedback(self, **post):
		""" Handle both redirection from Ingenico (GET) and s2s notification (POST/GET) """
		_logger.info('Ogone: entering form_feedback with post data %s', pprint.pformat(post))  # debug
		request.env['payment.transaction'].sudo().form_feedback(post, 'ogone')
		return werkzeug.utils.redirect("/payment/process")

	@http.route(['/payment/ogone/s2s/create_json'], type='json', auth='public', csrf=False)
	def ogone_s2s_create_json(self, **kwargs):
		if not kwargs.get('partner_id'):
			kwargs = dict(kwargs, partner_id=request.env.user.partner_id.id)
		token_s2s_process = request.env['payment.acquirer'].browse(int(kwargs.get('acquirer_id'))).s2s_process(kwargs)
		return token_s2s_process.id

	@http.route(['/payment/ogone/s2s/create_json_3ds'], type='json', auth='public', csrf=False)
	def ogone_s2s_create_json_3ds(self, verify_validity=False, **kwargs):
		if not kwargs.get('partner_id'):
			kwargs = dict(kwargs, partner_id=request.env.user.partner_id.id)
		token_s2s_process = False
		error = None

		try:
			token_s2s_process = request.env['payment.acquirer'].browse(int(kwargs.get('acquirer_id'))).s2s_process(kwargs)
		except Exception as e:
			error = str(e)

		if not token_s2s_process:
			result_create_json_3ds = {
				'result': False,
				'error': error,
			}
			return result_create_json_3ds

		result_create_json_3ds = {
			'result': True,
			'id': token_s2s_process.id,
			'short_name': token_s2s_process.short_name,
			'3d_secure': False,
			'verified': False,
		}

		if verify_validity != False:
			baseurl = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
			params = {
				'accept_url': baseurl + '/payment/ogone/validate/accept',
				'decline_url': baseurl + '/payment/ogone/validate/decline',
				'exception_url': baseurl + '/payment/ogone/validate/exception',
				'return_url': kwargs.get('return_url', baseurl)
				}
			tx = token_s2s_process.validate(**params)
			result_create_json_3ds['verified'] = token_s2s_process.verified

			if tx and tx.html_3ds:
				result_create_json_3ds['3d_secure'] = tx.html_3ds

		return result_create_json_3ds

	@http.route(['/payment/ogone/s2s/create'], type='http', auth='public', methods=["POST"], csrf=False)
	def ogone_s2s_create(self, **post):
		error = ''
		acq = request.env['payment.acquirer'].browse(int(post.get('acquirer_id')))
		try:
			token_s2s_process = acq.s2s_process(post)
		except Exception as e:
			# synthax error: 'CHECK ERROR: |Not a valid date\n\n50001111: None'
			token_s2s_process = False
			error = str(e).splitlines()[0].split('|')[-1] or ''

		if token_s2s_process and post.get('verify_validity'):
			baseurl = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
			params = {
				'accept_url': baseurl + '/payment/ogone/validate/accept',
				'decline_url': baseurl + '/payment/ogone/validate/decline',
				'exception_url': baseurl + '/payment/ogone/validate/exception',
				'return_url': post.get('return_url', baseurl)
				}
			tx = token_s2s_process.validate(**params)
			if tx and tx.html_3ds:
				return tx.html_3ds
			# add the payment transaction into the session to let the page /payment/process to handle it
			PaymentProcessing.add_payment_transaction(tx)
		return werkzeug.utils.redirect("/payment/process")

	@http.route([
		'/payment/ogone/validate/accept',
		'/payment/ogone/validate/decline',
		'/payment/ogone/validate/exception',
	], type='http', auth='public')
	def ogone_validation_form_feedback(self, **post):
		""" Feedback from 3d secure for a bank card validation """
		request.env['payment.transaction'].sudo().form_feedback(post, 'ogone')
		return werkzeug.utils.redirect("/payment/process")

	@http.route(['/payment/ogone/s2s/feedback'], auth='public', csrf=False)
	def feedback(self, **kwargs):
		try:
			tx = request.env['payment.transaction'].sudo()._ogone_form_get_tx_from_data(kwargs)
			tx._ogone_s2s_validate_tree(kwargs)
		except ValidationError:
			return 'ko'
		return 'ok'
