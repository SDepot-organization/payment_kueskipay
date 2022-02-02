# -*- coding: utf-8 -*-
import logging
import pprint
import werkzeug

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class KueskiPayController(http.Controller):
	_accept_url = '/payment/kueskipay/feedback'
	@http.route([
		'/payment/kueskipay/feedback',
	], type='http', auth='public', csrf=False)
	def kueskipay_form_feedback(self, **post):
		_logger.info('Beginning form_feedback with post data %s', pprint.pformat(post))  # debug
		request.env['payment.transaction'].sudo().form_feedback(post, 'kueskipay')
		return werkzeug.utils.redirect('/payment/process')

	@http.route([
		'/payment/kueskipay/draft',
		'/payment/kueskipay/pending',
		'/payment/kueskipay/authorized',
		'/payment/kueskipay/done',
		'/payment/kueskipay/cancel',
		'/payment/kueskipay/error',
	], type='http', auth='public', csrf=False)
	def kueskipay_form_feedback2(self, route=None, **post):
		'''
		aqui se necesita una respuesta en texto plano, pero no encuentro como
		'''
		_logger.info('Beginning form_feedback with post data %s', pprint.pformat(post))  # debug
		request.env['payment.transaction'].sudo().form_feedback(post, 'kueskipay')
		return werkzeug.utils.redirect('/payment/process')#<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">\n<title>Redirecting...</title>\n<h1>Redirecting...</h1>\n<p>You should be redirected automatically to target URL: <a href="/payment/process">/payment/process</a>.  If not click the link.
