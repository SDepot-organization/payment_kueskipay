# -*- coding: utf-8 -*-
from odoo import models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def write(self, vals):
        """
            override of write to detect a change in the commercial_partner_id
            In such case, we need to remove all existing sdd tokens as the
            partner won't be able to use them anymore.
        """
        commercial_partners = {}
        partners_with_new_commercial = self.env['res.partner']
        for partner in self:
            commercial_partners[partner.id] = partner.commercial_partner_id

        res = super().write(vals)

        for partner in self:
            if commercial_partners[partner.id] != partner.commercial_partner_id:
                partners_with_new_commercial |= partner

        if partners_with_new_commercial:
            self.env['payment.token'].sudo().search([
                ('partner_id', 'in', partners_with_new_commercial.ids),
                ('acquirer_id.provider', '=', 'sepa_direct_debit')
            ]).unlink()

        return res
