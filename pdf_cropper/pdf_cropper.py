import asyncio
import platform
import os
from tkinter import filedialog
from tkinter import Tk
from PyPDF2 import PdfReader, PdfWriter
from pdf2image import convert_from_path
from PIL import Image, ImageDraw
import eel
import base64
from io import BytesIO
import numpy as np

# Initialize Eel for web GUI
eel.init('web')


@eel.expose
def select_pdf():
    root = Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
    if file_path:
        # Convert PDF to images for preview (all pages)
        images = convert_from_path(file_path)
        img = images[0]  # Use first page for preview
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        return {"path": file_path, "image": img_str}
    return None


@eel.expose
def crop_pdf(pdf_path, crop_regions):
    try:
        # Convert PDF to images for preview
        images = convert_from_path(pdf_path)
        img = images[0]  # Use first page for preview
        img_width, img_height = img.size

        # Create preview image with selected areas whited out
        preview_img = Image.new('RGB', (img_width, img_height), 'white')
        preview_img.paste(img, (0, 0))
        draw = ImageDraw.Draw(preview_img)
        for region in crop_regions:
            x1, y1, x2, y2 = region
            draw.rectangle((x1, y1, x2, y2), fill='white')

        buffered = BytesIO()
        preview_img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()

        # Process PDF cropping
        reader = PdfReader(pdf_path)
        writer = PdfWriter()

        for page in reader.pages:
            # Get original page dimensions
            orig_width = float(page.mediabox.width)
            orig_height = float(page.mediabox.height)

            # Process each crop region
            temp_pages = [page]  # Start with the original page
            for region in crop_regions:
                x1, y1, x2, y2 = region
                # Scale canvas coordinates to PDF coordinates
                scale_x = orig_width / img_width
                scale_y = orig_height / img_height
                pdf_x1 = x1 * scale_x
                pdf_y1 = (img_height - y2) * scale_y
                pdf_x2 = x2 * scale_x
                pdf_y2 = (img_height - y1) * scale_y

                new_temp_pages = []
                for temp_page in temp_pages:
                    # Add regions around the crop area
                    # Top region
                    if pdf_y2 < orig_height:
                        writer.add_page(temp_page)
                        top_page = writer.pages[-1]
                        top_page.mediabox.lower_left = (0, pdf_y2)
                        top_page.mediabox.upper_right = (orig_width, orig_height)
                        new_temp_pages.append(top_page)

                    # Bottom region
                    if pdf_y1 > 0:
                        writer.add_page(temp_page)
                        bottom_page = writer.pages[-1]
                        bottom_page.mediabox.lower_left = (0, 0)
                        bottom_page.mediabox.upper_right = (orig_width, pdf_y1)
                        new_temp_pages.append(bottom_page)

                    # Left region (between y1 and y2)
                    if pdf_x1 > 0:
                        writer.add_page(temp_page)
                        left_page = writer.pages[-1]
                        left_page.mediabox.lower_left = (0, pdf_y1)
                        left_page.mediabox.upper_right = (pdf_x1, pdf_y2)
                        new_temp_pages.append(left_page)

                    # Right region (between y1 and y2)
                    if pdf_x2 < orig_width:
                        writer.add_page(temp_page)
                        right_page = writer.pages[-1]
                        right_page.mediabox.lower_left = (pdf_x2, pdf_y1)
                        right_page.mediabox.upper_right = (orig_width, pdf_y2)
                        new_temp_pages.append(right_page)

                temp_pages = new_temp_pages if new_temp_pages else [temp_page]

        # Remove blank pages
        final_writer = PdfWriter()
        temp_pdf = "temp_check.pdf"
        with open(temp_pdf, "wb") as temp_file:
            writer.write(temp_file)

        # Re-read the temporary PDF to convert pages to images
        temp_reader = PdfReader(temp_pdf)
        temp_images = convert_from_path(temp_pdf)

        for i, page in enumerate(temp_reader.pages):
            is_blank = True
            # Check page dimensions
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            if width < 1 or height < 1:
                continue  # Skip degenerate pages

            # Check content stream
            if "/Contents" in page:
                contents = page["/Contents"]
                if isinstance(contents, list):
                    for content in contents:
                        try:
                            data = content.get_object().get_data()
                            if data and data.strip() and not data.isspace():
                                is_blank = False
                                break
                        except:
                            pass
                else:
                    try:
                        data = contents.get_object().get_data()
                        if data and data.strip() and not data.isspace():
                            is_blank = False
                    except:
                        pass

            # Check resources (ignore /ProcSet alone)
            if is_blank and "/Resources" in page:
                resources = page["/Resources"]
                if resources.get("/XObject") or resources.get("/Font"):
                    is_blank = False

            # Image-based check for blank pages
            if is_blank and i < len(temp_images):
                img = temp_images[i].convert('L')  # Convert to grayscale
                img_array = np.array(img)
                # Check if all pixels are white (255) or near-white (>250)
                if not np.all(img_array > 250):
                    is_blank = False

            # Add non-blank pages
            if not is_blank:
                final_writer.add_page(page)

        # Clean up temporary file
        os.remove(temp_pdf)

        # Save temporary cropped PDF
        temp_output = "temp_cropped.pdf"
        with open(temp_output, "wb") as output_file:
            final_writer.write(output_file)

        return {"image": img_str, "pdf_path": temp_output, "page_count": len(final_writer.pages)}
    except Exception as e:
        return {"error": str(e)}


@eel.expose
def save_cropped_pdf(temp_path, selected_pages):
    try:
        root = Tk()
        root.withdraw()
        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if not save_path:
            return None

        # Read the temporary PDF
        reader = PdfReader(temp_path)
        writer = PdfWriter()

        # Add only selected pages (0-based index)
        for page_num in selected_pages:
            if 0 <= page_num < len(reader.pages):
                writer.add_page(reader.pages[page_num])

        # Save the final PDF
        with open(save_path, "wb") as output_file:
            writer.write(output_file)

        return save_path
    except Exception as e:
        return {"error": str(e)}


async def main():
    try:
        # Start Eel server
        eel.start('index.html', size=(800, 600), port=0)
    except Exception as e:
        print(f"Error starting Eel: {e}")


if platform.system() == "Emscripten":
    asyncio.ensure_future(main())
else:
    if __name__ == "__main__":
        asyncio.run(main())