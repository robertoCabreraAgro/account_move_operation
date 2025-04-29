# models/account_move.py (updated version)
from odoo import models, fields, api, _


class AccountMove(models.Model):
    _inherit = "account.move"

    operation_line_ids = fields.One2many(
        "account.move.operation.line",
        "move_id",
        string="Operation Lines",
        readonly=True,
    )
    
    operation_id = fields.Many2one(
        "account.move.operation",
        string="Source Operation",
        compute="_compute_operation_id",
        store=True,
    )
    
    @api.depends('operation_line_ids.operation_id')
    def _compute_operation_id(self):
        for move in self:
            move.operation_id = move.operation_line_ids[:1].operation_id.id

    def action_post(self):
        opertation_line_obj = self.env["account.move.operation.line"]
        res = super().action_post()
        for rec in self.filtered(lambda am: am.state == "posted"):
            line = opertation_line_obj.search(
                [("action", "=", "move"), ("state", "=", "in_progress"), ("move_id", "=", rec.id)], limit=1
            )
            if line:
                line.action_done()
        return res
    
    def action_create_operation(self):
        """Open wizard to create an operation from this entry"""
        self.ensure_one()
        return {
            'name': _('Create Operation From Entry'),
            'view_mode': 'form',
            'res_model': 'account.move.operation.from.entry',
            'view_id': self.env.ref('account_move_operation.view_account_move_operation_from_entry_form').id,
            'type': 'ir.actions.act_window',
            'context': {
                'default_move_id': self.id,
            },
            'target': 'new',
        }
    
    def action_view_operation(self):
        """View the related operation"""
        self.ensure_one()
        if not self.operation_id:
            return False
            
        return {
            'name': _('Account Operation'),
            'view_mode': 'form',
            'res_model': 'account.move.operation',
            'res_id': self.operation_id.id,
            'type': 'ir.actions.act_window',
        }