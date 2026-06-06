from .models import ParametresAssociation
from .permissions import peut_acceder_planning


def params_association(request):
    return {'params': ParametresAssociation.get()}


def planning_access(request):
    """Expose le droit d'accès au module Planning à tous les templates (sidebar)."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {'peut_acceder_planning': False}
    return {'peut_acceder_planning': peut_acceder_planning(user)}