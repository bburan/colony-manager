"""Smoke coverage for the ``data_files`` blueprint.

Two routes, both protected by login. The full success path requires
a real file on disk + a matching Data row; these tests focus on the
404 path so they cover the ``db.get_or_404`` conversion without
needing the PIL/thumbnail stack.
"""


def test_view_raw_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.get('/data/99999/raw')
    assert response.status_code == 404


def test_view_thumbnail_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.get('/data/99999/thumbnail')
    assert response.status_code == 404
