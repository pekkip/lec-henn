from django.db import migrations


def set_zone_financement(apps, schema_editor):
    Devis = apps.get_model('core', 'Devis')
    LigneDevis = apps.get_model('core', 'LigneDevis')
    devis_avec_fin = LigneDevis.objects.filter(
        type_ligne='FIN', parent=None
    ).values_list('devis_id', flat=True).distinct()
    Devis.objects.filter(pk__in=devis_avec_fin).update(zone_financement=True)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_bibliothequeaides_zone_financement'),
    ]

    operations = [
        migrations.RunPython(set_zone_financement, migrations.RunPython.noop),
    ]
