import re

import pytest
from apps.db_transfers.forms import DbTransferForm
from apps.connections.models import KIND_MYSQL, KIND_MSSQL


@pytest.mark.django_db
class TestDbTransferFormEngineFiltering:
    def test_mysql_engine_only_offers_mysql_connections(self, regular_user, make_connection):
        mysql_conn = make_connection(regular_user, kind=KIND_MYSQL, db_name='a')
        mssql_conn = make_connection(regular_user, kind=KIND_MSSQL, db_name='b')
        form = DbTransferForm(user=regular_user, engine=KIND_MYSQL)
        qs_pks = set(form.fields['source_connection'].queryset.values_list('pk', flat=True))
        assert mysql_conn.pk in qs_pks
        assert mssql_conn.pk not in qs_pks

    def test_mismatched_source_dest_kind_invalid(self, regular_user, make_connection):
        mysql_conn = make_connection(regular_user, kind=KIND_MYSQL, db_name='a')
        mssql_conn = make_connection(regular_user, kind=KIND_MSSQL, db_name='b')
        form = DbTransferForm(
            {'source_connection': mysql_conn.pk, 'dest_connection': mssql_conn.pk, 'scope': 'whole_db'},
            user=regular_user, engine=KIND_MYSQL,
        )
        assert not form.is_valid()

    def test_unbound_form_with_engine_kwarg_sets_engine_field_initial(self, regular_user):
        form = DbTransferForm(user=regular_user, engine=KIND_MYSQL)
        assert form.fields['engine'].initial == KIND_MYSQL

    def test_unbound_form_with_engine_kwarg_renders_correct_radio_checked(self, regular_user):
        form = DbTransferForm(user=regular_user, engine=KIND_MYSQL)
        rendered = str(form['engine'])
        mysql_input = re.search(r'<input[^>]*value="mysql"[^>]*>', rendered).group(0)
        postgres_input = re.search(r'<input[^>]*value="postgres"[^>]*>', rendered).group(0)
        assert 'checked' in mysql_input
        assert 'checked' not in postgres_input
