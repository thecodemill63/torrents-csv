"""Torrent model — a read-only mapping to the existing `torrents` table.

`managed = False` so Django never tries to create/alter the table; the sync
pipeline owns the schema. We also skip migrations for this app.
"""
from django.db import models


class Torrent(models.Model):
    infohash = models.CharField(primary_key=True, max_length=40)
    name = models.TextField()
    size_bytes = models.BigIntegerField(null=True)
    created_unix = models.BigIntegerField(null=True)
    seeders = models.IntegerField(null=True)
    leechers = models.IntegerField(null=True)
    completed = models.BigIntegerField(null=True)
    scraped_date = models.BigIntegerField(null=True)
    published = models.BigIntegerField(null=True)
    magnet = models.TextField()
    first_seen_local = models.BigIntegerField()
    last_updated_local = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = "torrents"
        ordering = ["-seeders"]

    def __str__(self):
        return self.name or self.infohash
