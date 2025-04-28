from odoo import models, fields, _
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

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
        
    def action_create_operation_from_move(self):
        """Crear una operación desde un asiento contable existente.
        
        Permite ejecutar un flujo de operaciones contables desde cualquier asiento
        existente (factura, pago, nota de crédito, etc.) y continuar el flujo sin 
        duplicar documentos ya existentes.
        """
        self.ensure_one()
        
        # Datos básicos que podemos extraer del asiento actual
        context = {
            'default_move_id': self.id,
            'default_partner_id': self.partner_id.id,
            'default_amount': self.amount_total,
            'default_ref': self.ref or self.name,
            'default_move_type': self.move_type,
            'default_currency_id': self.currency_id.id,
        }
        
        # Abrimos el asistente para seleccionar el tipo de operación
        return {
            'name': _('Create Operation from Journal Entry'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.operation.from.move',
            'view_mode': 'form',
            'target': 'new',
            'context': context,
        }
        
    def button_create_operation_from_move(self):
        """Botón para crear operación desde asiento contable.
        
        Este método es idéntico a action_create_operation_from_move pero se expone
        como botón en la vista de formulario de asientos contables.
        """
        return self.action_create_operation_from_move()
