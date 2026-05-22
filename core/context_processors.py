from .models import ParametresAssociation

def params_association(request):
    return {'params': ParametresAssociation.get()}