from . import meetings, officers, events, finance, plans, documents
import storage


def register_routes(app):
    app.register_blueprint(storage.bp)
    for module in (meetings, officers, events, finance, plans, documents):
        app.register_blueprint(module.bp)
