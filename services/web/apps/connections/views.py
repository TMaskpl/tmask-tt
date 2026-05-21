from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .models import Connection
from .forms import ConnectionForm
from .ssh_tester import test_connection as _test_connection

@login_required
def connection_list(request):
    connections = Connection.objects.filter(owner=request.user)
    return render(request, 'connections/list.html', {'connections': connections})

@login_required
def connection_create(request):
    form = ConnectionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        conn = form.save(commit=False)
        conn.owner = request.user
        conn.save()
        return redirect('connections:list')
    return render(request, 'connections/form.html', {'form': form, 'action': 'CREATE'})

@login_required
def connection_edit(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    form = ConnectionForm(request.POST or None, instance=conn)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('connections:list')
    return render(request, 'connections/form.html', {'form': form, 'action': 'EDIT', 'conn': conn})

@login_required
@require_POST
def connection_delete(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    conn.delete()
    return redirect('connections:list')

@login_required
def connection_test(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    result = _test_connection(conn)
    return JsonResponse({'success': result.success, 'message': result.message})
