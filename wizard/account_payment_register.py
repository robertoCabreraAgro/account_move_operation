from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def _create_payments(self):
        payments = super()._create_payments()
        if self._context.get("operation_line_id"):
            line = self.env["account.move.operation.line"].browse(self._context.get("operation_line_id"))
            line.payment_id = payments[:1]
            line.action_done()
        return payments
