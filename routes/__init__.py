from . import meetings, officers, events, finance, plans, documents, donations, budget, official, vouchers, settlement
import auth
import storage


def register_routes(app):
    app.register_blueprint(auth.bp)
    app.register_blueprint(storage.bp)
    for module in (meetings, officers, events, finance, plans, documents, donations, budget, official, vouchers, settlement):
        app.register_blueprint(module.bp)
