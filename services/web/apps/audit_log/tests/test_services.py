import pytest

from apps.audit_log.models import ConfigAuditLog, ACTION_CREATED, ACTION_UPDATED, ACTION_DELETED
from apps.audit_log.services import log_created, log_updated, log_deleted, diff_fields


@pytest.mark.django_db
class TestLogCreated:
    def test_creates_entry_with_correct_fields(self, regular_user, make_connection):
        conn = make_connection(regular_user, name='Prod')
        log_created(regular_user, conn)
        entry = ConfigAuditLog.objects.get()
        assert entry.user == regular_user
        assert entry.model_name == 'Connection'
        assert entry.object_id == conn.pk
        assert entry.action == ACTION_CREATED
        assert 'Prod' in entry.object_repr
        assert entry.changed_fields == {}


@pytest.mark.django_db
class TestLogUpdated:
    def test_creates_entry_with_changed_fields(self, regular_user, make_connection):
        conn = make_connection(regular_user, name='Prod')
        log_updated(regular_user, conn, {'host': ['1.2.3.4', '5.6.7.8']})
        entry = ConfigAuditLog.objects.get()
        assert entry.action == ACTION_UPDATED
        assert entry.changed_fields == {'host': ['1.2.3.4', '5.6.7.8']}

    def test_skips_entry_when_no_changes(self, regular_user, make_connection):
        conn = make_connection(regular_user, name='Prod')
        log_updated(regular_user, conn, {})
        assert ConfigAuditLog.objects.count() == 0


@pytest.mark.django_db
class TestLogDeleted:
    def test_creates_entry_before_object_gone(self, regular_user, make_connection):
        conn = make_connection(regular_user, name='Prod')
        pk = conn.pk
        log_deleted(regular_user, conn)
        entry = ConfigAuditLog.objects.get()
        assert entry.action == ACTION_DELETED
        assert entry.object_id == pk


class TestDiffFields:
    def test_detects_changed_field(self):
        class Obj:
            def __init__(self, host):
                self.host = host
        old, new = Obj('1.1.1.1'), Obj('2.2.2.2')
        assert diff_fields(old, new, ['host']) == {'host': ['1.1.1.1', '2.2.2.2']}

    def test_ignores_unchanged_field(self):
        class Obj:
            def __init__(self, host):
                self.host = host
        old, new = Obj('1.1.1.1'), Obj('1.1.1.1')
        assert diff_fields(old, new, ['host']) == {}

    def test_secret_field_masked_not_leaked(self):
        class Obj:
            def __init__(self, password):
                self.password = password
        old, new = Obj('old-secret'), Obj('new-secret')
        result = diff_fields(old, new, ['password'], secret_fields={'password'})
        assert result == {'password': ['***', '***']}
        assert 'old-secret' not in str(result)
        assert 'new-secret' not in str(result)

    def test_none_and_empty_string_are_not_a_change(self):
        class Obj:
            def __init__(self, ssh_key):
                self.ssh_key = ssh_key
        old, new = Obj(None), Obj('')
        assert diff_fields(old, new, ['ssh_key']) == {}
        old, new = Obj(''), Obj(None)
        assert diff_fields(old, new, ['ssh_key']) == {}

    def test_multiple_fields_only_changed_ones_included(self):
        class Obj:
            def __init__(self, a, b):
                self.a = a
                self.b = b
        old, new = Obj('x', 'same'), Obj('y', 'same')
        assert diff_fields(old, new, ['a', 'b']) == {'a': ['x', 'y']}
