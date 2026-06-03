"""Route the analytics app to the dedicated warehouse database."""


class AnalyticsRouter:
    route_app_labels = {"analytics"}

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.route_app_labels:
            return "analytics"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label in self.route_app_labels:
            return "analytics"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if (
            obj1._meta.app_label in self.route_app_labels
            or obj2._meta.app_label in self.route_app_labels
        ):
            return False
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.route_app_labels:
            return db == "analytics"
        if db == "analytics":
            return False
        return None
