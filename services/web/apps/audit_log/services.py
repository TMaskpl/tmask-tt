from .models import ConfigAuditLog, ACTION_CREATED, ACTION_UPDATED, ACTION_DELETED


def log_created(user, instance) -> None:
    ConfigAuditLog.objects.create(
        user=user, model_name=type(instance).__name__, object_id=instance.pk,
        object_repr=str(instance), action=ACTION_CREATED,
    )


def log_updated(user, instance, changed_fields: dict) -> None:
    if not changed_fields:
        return
    ConfigAuditLog.objects.create(
        user=user, model_name=type(instance).__name__, object_id=instance.pk,
        object_repr=str(instance), action=ACTION_UPDATED, changed_fields=changed_fields,
    )


def log_deleted(user, instance) -> None:
    ConfigAuditLog.objects.create(
        user=user, model_name=type(instance).__name__, object_id=instance.pk,
        object_repr=str(instance), action=ACTION_DELETED,
    )


def _normalize(value):
    """None and '' are the same "empty" to a human reading an audit log — some
    model fields still allow null=True while their ModelForm counterpart
    round-trips an untouched blank value as '', which would otherwise show up
    as a spurious changed_fields entry on every edit that doesn't touch that
    field at all."""
    return '' if value is None else value


def diff_fields(old_instance, new_instance, fields: list, secret_fields: set | None = None) -> dict:
    """Compares tracked fields between two instances. Secret/opaque fields
    (passwords, keys, host key blobs) are recorded as changed without ever
    storing their value — only non-secret fields get before/after in the log."""
    secret_fields = secret_fields or set()
    changes = {}
    for field in fields:
        old_val = getattr(old_instance, field)
        new_val = getattr(new_instance, field)
        if _normalize(old_val) == _normalize(new_val):
            continue
        if field in secret_fields:
            changes[field] = ['***', '***']
        else:
            changes[field] = [str(old_val), str(new_val)]
    return changes
