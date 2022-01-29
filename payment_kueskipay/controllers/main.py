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
