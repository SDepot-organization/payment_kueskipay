# -*- coding: utf-8 -*-
{
	'name':						'Kueskipay Payment Acquirer',
	'description':				'''Kueskipay Payment Acquirer''',
	'summary':					'''
	Payment Acquirer:			Kueskipay Implementation
	Licencias
	license:					CC BY-NC-ND 4.0
								''',
	'author':					'caballeroantonio',
	'website':					'http://caballeroantonio.ddns.net',
	'category':					'Accounting/Payment Acquirers',
	'version':					'1.0',
	'depends':					['payment', 'sms'],#'website_sale' recursivo
	'external_dependencies':	{'python': []},
	'data':						[
									'views/payment_views.xml',
									'views/payment_kueskipay_templates.xml',
									'data/payment_acquirer_data.xml',
								],
	'demo':						[
								],
	'auto_install':				False,
	'price':					169,
	'currency':					'USD',
	'application':				True,
	'installable':				True,
	'license':					'Other proprietary',
	'maintainer':				'caballeroantonio@hotmail.com',
	'post_init_hook':			'create_missing_journal_for_acquirers',
	'uninstall_hook':			'uninstall_hook',
}
