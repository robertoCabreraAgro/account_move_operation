from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval


class AccountMoveOperationLine(models.Model):
    _name = "account.move.operation.line"
    _description = "Account Move Operation Lines"

    operation_id = fields.Many2one(
        comodel_name="account.move.operation",
        required=True,
        readonly=True,
    )
    name = fields.Char(required=True, readonly=True)
    state = fields.Selection(
        selection=[
            ("waiting", "Waiting"),
            ("ready", "Ready"),
            ("done", "Done"),
            ("cancel", "Cancel"),
            ("in_progress", "In Progress"),
            # ("waiting_operation", "Waiting another operation"),
        ],
        default="draft",
        copy=False,
        readonly=True,
    )
    orig_line_id = fields.Many2one(
        comodel_name="account.move.operation.line",
        readonly=True,
        compute="_compute_orig_line",
        inverse="_inverse_orig_line",
        store=True,
    )
    dest_line_id = fields.Many2one(
        comodel_name="account.move.operation.line",
        readonly=True,
        compute="_compute_dest_line",
        inverse="_inverse_dest_line",
        store=True,
    )
    action = fields.Selection(
        selection=[
            ("move", "Create Journal Entry"),
            ("pay", "Create Payment"),
            ("reconcile", "Reconcile Payment"),
            ("operation", "Create Operation"),
            ("info", "Information"),
        ],
        required=True,
        index=True,
    )
    action_id = fields.Many2one("account.move.operation.action", readonly=True)
    template_id = fields.Many2one(
        "account.move.template", "Move Template", readonly=True
    )
    journal_id = fields.Many2one("account.journal", "Journal", readonly=True)
    move_id = fields.Many2one("account.move", readonly=True)
    payment_id = fields.Many2one("account.payment", readonly=True)
    st_line_id = fields.Many2one("account.bank.statement.line", readonly=True)
    created_operation_id = fields.Many2one("account.move.operation", readonly=True)
    date_last_document = fields.Boolean(
        readonly=True,
        help="When creating an invoice, set the date to be the same of the previous document, "
        "being it a payment or invoice.",
    )
    diff_partner = fields.Boolean(
        string="Different Partner",
        readonly=True,
        help="Enables use of a different partner than the one set on the operation",
    )
    multicompany = fields.Boolean(string="Is Multicompany")

    @api.depends("orig_line_id.dest_line_id")
    def _compute_orig_line(self):
        for record in self.sudo():
            record.orig_line_id = (
                record.orig_line_id
                if record.orig_line_id.dest_line_id == record
                else False
            )

    def _inverse_orig_line(self):
        for record in self.sudo():
            record.orig_line_id.dest_line_id = record

    @api.depends("dest_line_id.orig_line_id")
    def _compute_dest_line(self):
        for record in self.sudo():
            record.dest_line_id = (
                record.dest_line_id
                if record.dest_line_id.orig_line_id == record
                else False
            )

    def _inverse_dest_line(self):
        for record in self.sudo():
            record.dest_line_id.orig_line_id = record

    def action_cancel(self):
        lines = self.filtered(lambda line: line.state not in ["done", "cancel"])
        lines.write({"state": "cancel"})
        for line in lines:
            if line.created_operation_id:
                operation = line.created_operation_id.sudo().with_company(
                    line.created_operation_id.company_id
                )
                operation.action_cancel()
            if (
                line.dest_line_id.operation_id
                and line.operation_id
                and line.dest_line_id.operation_id != line.operation_id
            ):
                dest_line = line.dest_line_id.sudo().with_company(
                    line.dest_line_id.operation_id.company_id
                )
                dest_line.operation_id.action_cancel()

    def action_done(self):
        self.state = "done"
        if self.dest_line_id and self.dest_line_id.state == "waiting":
            self.dest_line_id.state = "ready"
        else:
            self.operation_id.action_done()
        if self.dest_line_id and self.dest_line_id.state == "in_progress":
            self.sudo().dest_line_id.action_done()

    def action_in_progress(self):
        self.write({"state": "in_progress"})

    def action_view_document(self):
        method_name = "action_view_document_%s" % self.action
        open_document_method = getattr(self, method_name)
        return open_document_method()

    def action_view_document_move(self):
        if not self.move_id:
            return False

        action = self.env["ir.actions.actions"]._for_xml_id(
            "account.action_move_journal_line"
        )
        action.update(
            {
                "name": _("Entry from template %s", self.template_id.name),
                "views": False,
                "view_id": False,
                "view_mode": "form",
                "context": self.env.context,
                "res_id": self.move_id.id,
            }
        )
        return action

    def action_view_document_pay(self):
        if not self.payment_id:
            return False

        action = {
            "name": _("Payments"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "context": {"create": False},
            "view_mode": "form",
            "res_id": self.payment_id.id,
        }
        return action

    def action_view_document_reconcile(self):
        if not self.st_line_id:
            return False

        action = {
            "name": _("Bank Statement Line"),
            "type": "ir.actions.act_window",
            "res_model": "account.bank.statement.line",
            "context": {"create": False},
            "view_mode": "form",
            "res_id": self.st_line_id.id,
        }
        return action

    def _get_action(self):
        self.ensure_one()
        action = self._get_action_move()
        if action:
            return action

        method_name = "_get_action_%s" % self.action
        get_action_method = getattr(self, method_name)
        return get_action_method()

    def _get_action_info(self):
        return self.action_done()

    def _get_action_move(self):
        self.ensure_one()
        ctx = self._context.copy()

        if self.action_id.auto and self.operation_id.amount:
            ctx.update({"amount": self.operation_id.amount})

        wizard_vals = {
            "template_id": self.template_id.id,
            "partner_id": self.operation_id.partner_id.id,
            "date": fields.Date.context_today(self),
            "ref": self.operation_id.reference or self.template_id.ref,
            "amount": self.operation_id.amount,
        }

        if self.diff_partner and self.operation_id.diff_partner_id:
            wizard_vals["diff_partner_id"] = self.operation_id.diff_partner_id.id
        if self.multicompany and self.operation_id.multicompany_id:
            wizard_vals["multicompany_id"] = self.operation_id.multicompany_id.id

        wizard = (
            self.env["account.move.template.run"].with_context(ctx).create(wizard_vals)
        )
        wizard.load_lines()
        result = wizard.create_move()

        if result._name == "account.move":
            self.move_id = result.id
        elif result._name == "account.payment":
            self.payment_id = result.id

        self.state = "done"

        if self.dest_line_id and self.dest_line_id.state == "waiting":
            self.dest_line_id.state = "ready"
        elif self.dest_line_id and self.dest_line_id.state == "in_progress":
            self.sudo().dest_line_id.action_done()
        elif not self.dest_line_id:
            self.operation_id.action_done()

        return True

    def _get_action_reconcile(self):
        if self.action_id.auto:
            move = self._get_latest_move()
            if not move:
                raise UserError(_("Missing invoice to reconcile"))

            wiz = self.env["account.move.operation.reconcile"].create(
                {
                    "partner_id": self.operation_id.partner_id.id,
                    "move_id": move.id,
                    "line_id": self.id,
                    "st_line_id": self.operation_id.st_line_id.id,
                }
            )
            return wiz.action_open_reconcile()

        action = self.env["ir.actions.actions"]._for_xml_id(
            "account_move_operation.account_move_operation_reconcile_action"
        )
        action = self._update_action_context(action)
        return action

    def _update_action_context(self, action):
        context = self._context.copy()
        if "context" in action and isinstance(action["context"], str):
            context.update(safe_eval(action["context"]))
        else:
            context.update(action.get("context", {}))
        action["context"] = context
        action["context"].update(
            {
                "active_model": self._name,
                "active_ids": self.ids,
            }
        )
        return action

    def _get_latest_move(self):
        if self.move_id:
            return self.move_id

        if self.orig_line_id:
            return self.orig_line_id._get_latest_move()

        return False

