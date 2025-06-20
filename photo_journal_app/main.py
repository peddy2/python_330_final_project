from datetime import datetime
import os
import time
from typing import Annotated

import aiofiles
from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi import HTTPException
from jinja2_fragments.fastapi import Jinja2Blocks
from PIL import Image
from tinydb import TinyDB, Query

os.makedirs("static/images", exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Blocks(directory="templates")


def get_db():
    return TinyDB("db.json")


PHOTOS_PER_PAGE = 3


# Utility functions

def get_sorted_photos(all_photos, current_photo_count, new_photo_count):
    return sorted(all_photos,
                  key=lambda d: datetime.strptime(d["uploaded_at"], "%m/%d/%Y %I:%M:%S%p"),
                  reverse=True)[current_photo_count:new_photo_count]


def resize_image_for_web(photo_file_path):
    image_file = Image.open(f"static/{photo_file_path}")
    if image_file.width > image_file.height and image_file.width > 1920:
        image_file.thumbnail((1920, 1080))
    if image_file.width < image_file.height and image_file.width > 900:
        image_file.thumbnail((900, 1200))
    image_file.save(f"static{photo_file_path}")


# FastAPI routes

@app.get("/", response_class=HTMLResponse)
def photo_journal(request: Request, db: TinyDB = Depends(get_db)):
    sorted_photos = get_sorted_photos(db.all(), 0, PHOTOS_PER_PAGE)
    context = {
        "request": request,
        "photos": sorted_photos,
        "photo_count": PHOTOS_PER_PAGE,
    }
    return templates.TemplateResponse(request=request, name="photo_journal.html.jinja2", context=context)


@app.post("/post-photo", response_class=HTMLResponse)
async def post_photo(request: Request, entry: Annotated[str, Form()], photo_upload: UploadFile,
                     db: TinyDB = Depends(get_db)):
    valid_image_file = True
    photo_file_path = f"/images/{photo_upload.filename}"
    async with aiofiles.open(f"static{photo_file_path}", "wb") as out_file:
        content = await photo_upload.read()
        await out_file.write(content)
        try:
            with Image.open(f"static{photo_file_path}") as image_file:
                image_file.verify()
        except (IOError, SyntaxError):
            valid_image_file = False
            os.remove(f"static{photo_file_path}")
    if valid_image_file:
        resize_image_for_web(photo_file_path)
        uploaded_at = time.strftime("%m/%d/%Y %I:%M:%S%p")
        db.insert({"entry": entry,
                   "file_path": photo_file_path,
                   "uploaded_at": uploaded_at})
    sorted_photos = get_sorted_photos(db.all(), 0, PHOTOS_PER_PAGE)
    context = {
        "request": request,
        "photos": sorted_photos,
        "photo_count": PHOTOS_PER_PAGE,
        "invalid_image_file": not valid_image_file,
    }
    return templates.TemplateResponse(request=request, name="photo_journal.html.jinja2", context=context,
                                      block_name="photos")


# FEATURE 1: Edit photo journal entries
@app.get("/edit-photo", response_class=HTMLResponse)
def get_edit_photo_form(request: Request, photo_id: int, cancel: bool = False, db: TinyDB = Depends(get_db)):
    photo = db.get(doc_id=photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    # If cancel is True, return the original display
    if cancel:
        return f'''
        <p class="mb-3 font-normal text-gray-700 cursor-pointer hover:bg-gradient-to-r hover:from-purple-50 hover:to-blue-50 p-3 rounded-lg border-2 border-transparent hover:border-purple-200 transition-all duration-200"
           hx-get="/edit-photo"
           hx-target="#photo-edit-fields-{photo.doc_id}"
           hx-swap="innerHTML"
           hx-vals='{{"photo_id": {photo.doc_id}}}'>
          {photo["entry"]}
        </p>
        '''
    else:
        # Return the edit form
        return f'''
        <form hx-post="/edit-photo"
              hx-target="#photo-edit-fields-{photo.doc_id}"
              hx-swap="innerHTML"
              class="space-y-3">
          <input name="photo_id" type="hidden" value="{photo.doc_id}">
          <textarea name="entry" 
                    rows="4"
                    class="block p-3 w-full text-sm text-gray-900 bg-purple-50 rounded-lg border-2 border-purple-200 focus:ring-purple-500 focus:border-purple-500 transition-all resize-none"
                    required>{photo["entry"]}</textarea>
          <div class="flex space-x-2">
            <button type="submit"
                    class="px-4 py-2 bg-gradient-to-r from-green-500 to-green-600 text-white text-sm font-semibold rounded-lg hover:from-green-600 hover:to-green-700 transition-all duration-200 transform hover:scale-105">
              ✅ Save
            </button>
            <button type="button"
                    class="px-4 py-2 bg-gradient-to-r from-gray-400 to-gray-500 text-white text-sm font-semibold rounded-lg hover:from-gray-500 hover:to-gray-600 transition-all duration-200"
                    hx-get="/edit-photo"
                    hx-target="#photo-edit-fields-{photo.doc_id}"
                    hx-swap="innerHTML"
                    hx-vals='{{"photo_id": {photo.doc_id}, "cancel": "true"}}'>
              ❌ Cancel
            </button>
          </div>
        </form>
        '''


@app.post("/edit-photo", response_class=HTMLResponse)
def edit_photo(request: Request, photo_id: Annotated[int, Form()], entry: Annotated[str, Form()],
               db: TinyDB = Depends(get_db)):
    db.update({'entry': entry}, doc_ids=[photo_id])
    updated_photo = db.get(doc_id=photo_id)

    # Return the updated display paragraph
    return f'''
    <p class="mb-3 font-normal text-gray-700 cursor-pointer hover:bg-gradient-to-r hover:from-purple-50 hover:to-blue-50 p-3 rounded-lg border-2 border-transparent hover:border-purple-200 transition-all duration-200"
       hx-get="/edit-photo"
       hx-target="#photo-edit-fields-{updated_photo.doc_id}"
       hx-swap="innerHTML"
       hx-vals='{{"photo_id": {updated_photo.doc_id}}}'>
      {updated_photo["entry"]}
    </p>
    '''


# FEATURE 2: Delete photos
@app.delete("/delete-photo")
def delete_photo(photo_id: int, db: TinyDB = Depends(get_db)):
    photo = db.get(doc_id=photo_id)
    if photo:
        # Remove the image file from the filesystem
        file_path = f"static{photo['file_path']}"
        if os.path.exists(file_path):
            os.remove(file_path)
        # Remove the photo record from the database
        db.remove(doc_ids=[photo_id])

    return Response(status_code=200)


# FEATURE 3: Infinite scroll for pagination
@app.get("/load-photos", response_class=HTMLResponse)
def load_photos(request: Request, photo_count: int, db: TinyDB = Depends(get_db)):
    new_photo_count = photo_count + PHOTOS_PER_PAGE
    new_photos = get_sorted_photos(db.all(), photo_count, new_photo_count)

    # If no new photos, return empty response
    if not new_photos:
        return Response(content="", status_code=200)

    context = {
        "request": request,
        "photos": new_photos,
        "photo_count": new_photo_count,
    }

    return templates.TemplateResponse(request=request, name="photo_journal.html.jinja2", context=context,
                                      block_name="photo_list")