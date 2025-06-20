import tempfile
from unittest.mock import patch
import io

from fastapi.testclient import TestClient
from PIL import Image
import pytest
from tinydb import TinyDB, Query

from .main import app, get_db, get_sorted_photos, PHOTOS_PER_PAGE


def override_get_db():
    return TinyDB("test.json")


app.dependency_overrides[get_db] = override_get_db
test_db = override_get_db()
client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_db():
    yield
    test_db.truncate()


def test_get_photo_journal():
    response = client.get("/")
    assert response.status_code == 200
    assert b'Photo Journal' in response.content


def post_photo_to_db(entry):
    # Create a simple image in memory
    image = Image.new('RGB', size=(100, 100), color='red')
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='JPEG')
    img_bytes.seek(0)

    # Use the in-memory image for the test
    response = client.post(
        "/post-photo",
        files={"photo_upload": ("test.jpg", img_bytes, "image/jpeg")},
        data={'entry': entry}
    )
    return response


@patch("photo_journal_app.main.resize_image_for_web")
@patch("aiofiles.open")
@patch("PIL.Image.open")
def test_post_new_photo(mock_image_open, mock_aio_open, mock_resize):
    response = post_photo_to_db('my awesome photo')
    assert response.status_code == 200
    assert b'my awesome photo' in response.content


@patch("photo_journal_app.main.resize_image_for_web")
@patch("aiofiles.open")
@patch("PIL.Image.open")
def test_edit_photo(mock_image_open, mock_open, mock_resize):
    response = post_photo_to_db('my cool photo')
    assert response.status_code == 200
    assert b'my cool photo' in response.content
    Photo = Query()
    photo_created = test_db.get(Photo.entry == 'my cool photo')
    response = client.post("/edit-photo", data={'entry': 'my super cool photo', 'photo_id': photo_created.doc_id})
    assert response.status_code == 200
    assert b'my super cool photo' in response.content
    assert b'my cool photo' not in response.content


@patch("os.remove")
@patch("photo_journal_app.main.resize_image_for_web")
@patch("aiofiles.open")
@patch("PIL.Image.open")
def test_delete_photo(mock_image_open, mock_open, mock_resize, mock_remove):
    response = post_photo_to_db('my great photo')
    assert response.status_code == 200
    assert b'my great photo' in response.content
    response = client.get("/")
    assert response.status_code == 200
    assert b'my great photo' in response.content
    Photo = Query()
    photo_created = test_db.get(Photo.entry == 'my great photo')
    client.delete("/delete-photo", params={'photo_id': photo_created.doc_id})
    response = client.get("/")
    assert response.status_code == 200
    assert b'my great photo' not in response.content


@patch("photo_journal_app.main.resize_image_for_web")
@patch("aiofiles.open")
@patch("PIL.Image.open")
def test_load_photos(mock_image_open, mock_open, mock_resize):
    photo_entries = ['my awesome photo', 'my cool photo', 'my great photo', 'my sweet photo', 'my groovy photo']
    for entry in photo_entries:
        post_photo_to_db(entry)
    # get 3 most recently uploaded photos using get_sorted_photos method
    photos_to_load = get_sorted_photos(test_db.all(), 0, PHOTOS_PER_PAGE)
    response = client.get("/")
    assert response.status_code == 200
    # only the 3 most recently uploaded photos should appear on initial page load
    for photo in photos_to_load:
        assert photo['entry'].encode() in response.content
    remaining_photo_entries = []
    for entry in photo_entries:
        if entry not in [photo['entry'] for photo in photos_to_load]:
            assert entry.encode() not in response.content
            remaining_photo_entries.append(entry)
    # calling the /load-photos endpoint returns the remaining 2 photos to be appended to the page
    response = client.get("/load-photos", params={'photo_count': PHOTOS_PER_PAGE})
    assert response.status_code == 200
    for entry in remaining_photo_entries:
        assert entry.encode() in response.content