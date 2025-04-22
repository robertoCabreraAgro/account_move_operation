{
    "name": "Account Move Operations",
    "version": "saas~18.2.1.0.0",
    "category": "Accounting",
    "summary": "Templates for recurring accounting operations",
    "author": "Vauxoo",
    "license": "AGPL-3",
    "depends": [
        "account_accountant",
        "account_move_template",
    ],
    "data": [
        # Security
        "security/ir.model.access.csv",
        "security/ir_rule.xml",

        # # Views
        "views/account_move_operation_type_views.xml",
        "views/account_move_operation_action_views.xml",
        "views/account_move_operation_views.xml",
        # # "views/bank_rec_widget_views.xml",
        # # Wizard
        # "wizard/account_invoice_template_run_view.xml",
        # "wizard/account_move_operation_partner_view.xml",
        # "wizard/account_move_operation_payment_view.xml",
        # "wizard/account_move_operation_reconcile_view.xml",
        # "wizard/account_move_operation_operation_view.xml",
        # "wizard/account_bank_statement_operation_view.xml",

        # Data
        "data/ir_sequence_data.xml",
    ],
    "demo": [
        "demo/res_company.xml",
        "demo/account_account.xml",
        "demo/account_journal.xml",
        "demo/product.xml",
        "demo/account_move_template.xml",
        "demo/account_move_operation_type.xml",
    ],
    # "assets": {
    #     "web.assets_backend": [
    #         "account_move_operation/static/src/components/**/*",
    #     ],
    # },
    "installable": True,
}
