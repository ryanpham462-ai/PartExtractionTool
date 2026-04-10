import streamlit as st
import numpy as np
from PIL import Image
import fitz
import io
import base64
from streamlit_drawable_canvas import st_canvas

st.set_page_config(layout="wide", page_title="Jianpu Snipper (Manual)", initial_sidebar_state="collapsed")

st.title("Jianpu Part Snipper - Fully Manual Mode")

# --- STATE MANAGEMENT ---
if 'pdf_doc' not in st.session_state: st.session_state.pdf_doc = None
if 'pdf_images' not in st.session_state: st.session_state.pdf_images = []
if 'current_page' not in st.session_state: st.session_state.current_page = 0

# Storing exactly what should be rendered initially for a given page/render cycle
if 'page_objects' not in st.session_state: st.session_state.page_objects = {} # p_idx -> list of dict objects
if 'redo_stack' not in st.session_state: st.session_state.redo_stack = {} # p_idx -> list of dict objects
if 'render_keys' not in st.session_state: st.session_state.render_keys = {} # p_idx -> int
if 'temp_canvas_objects' not in st.session_state: st.session_state.temp_canvas_objects = {} # p_idx -> list of dict objects

uploaded_file = st.file_uploader("Upload Scanned Score PDF", type="pdf")

if uploaded_file is not None:
    if st.session_state.pdf_doc is None: # Process once
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        st.session_state.pdf_doc = doc
        if 'page_disp_images' not in st.session_state: st.session_state.page_disp_images = {}
        images = []
        MAX_DISPLAY_WIDTH = 900
        
        with st.spinner("Loading and pre-caching pages..."):
            for p_num in range(len(doc)):
                page = doc.load_page(p_num)
                pix = page.get_pixmap(dpi=150)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                img_np = np.array(img)
                images.append(img_np)
                
                # Pre-cache display images to prevent UI blackout during fast navigation
                scale = min(1.0, MAX_DISPLAY_WIDTH / img_np.shape[1])
                disp_w = int(img_np.shape[1] * scale)
                disp_h = int(img_np.shape[0] * scale)
                disp_img = Image.fromarray(img_np).resize((disp_w, disp_h), Image.Resampling.LANCZOS).convert("RGBA")
                
                # Base64 encode the image to fundamentally bypass Streamlit Cloud's broken Media Server
                buffered = io.BytesIO()
                disp_img.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                
                st.session_state.page_disp_images[p_num] = f"data:image/png;base64,{img_str}"
                
                st.session_state.page_objects[p_num] = []
                st.session_state.redo_stack[p_num] = []
                st.session_state.render_keys[p_num] = 0
                
        st.session_state.pdf_images = images

    images = st.session_state.pdf_images
    total_pages = len(images)
    p_idx = st.session_state.current_page
    
    tabs = st.tabs(["1. Snip Pages", "2. Preview & Export"])

    with tabs[0]:
        st.info("Draw bounding boxes over every section you want to extract on this page. Draw as many as you need! Use the buttons below to fix mistakes.")
        
        # --- CALLBACK LOGIC ---
        # Callbacks execute securely before the rest of the script, preventing double-renders & flashing
        def commit_canvas_state():
            c_idx = st.session_state.current_page
            if c_idx in st.session_state.temp_canvas_objects:
                st.session_state.page_objects[c_idx] = st.session_state.temp_canvas_objects[c_idx].copy()
        
        def nav_prev():
            commit_canvas_state()
            st.session_state.current_page -= 1
        
        def nav_next():
            commit_canvas_state()
            st.session_state.current_page += 1
            
        def do_undo():
            commit_canvas_state()
            c_idx = st.session_state.current_page
            if st.session_state.page_objects[c_idx]:
                obj = st.session_state.page_objects[c_idx].pop()
                st.session_state.redo_stack[c_idx].append(obj)
                st.session_state.render_keys[c_idx] += 1
                st.session_state.temp_canvas_objects[c_idx] = st.session_state.page_objects[c_idx].copy()
                
        def do_redo():
            commit_canvas_state()
            c_idx = st.session_state.current_page
            if st.session_state.redo_stack[c_idx]:
                obj = st.session_state.redo_stack[c_idx].pop()
                st.session_state.page_objects[c_idx].append(obj)
                st.session_state.render_keys[c_idx] += 1
                st.session_state.temp_canvas_objects[c_idx] = st.session_state.page_objects[c_idx].copy()
                
        def do_clear():
            c_idx = st.session_state.current_page
            st.session_state.page_objects[c_idx] = []
            st.session_state.redo_stack[c_idx] = []
            st.session_state.render_keys[c_idx] += 1
            st.session_state.temp_canvas_objects[c_idx] = []

        # Control Row Top
        c1, c2, c3, c4, c5, c6 = st.columns([1,1,1,1,1,1])
        c1.button("⬅️ Previous", on_click=nav_prev, disabled=(p_idx == 0), key="prev_top")
        c2.write(f"**Page {p_idx + 1} of {total_pages}**")
        c3.button("Next ➡️", on_click=nav_next, disabled=(p_idx == total_pages - 1), key="next_top")
        c4.button("↩️ Undo", on_click=do_undo, key="undo_top")
        c5.button("↪️ Redo", on_click=do_redo, key="redo_top")
        c6.button("🗑️ Delete All", on_click=do_clear, key="del_top")

        page_img_np = images[p_idx]
        
        MAX_DISPLAY_WIDTH = 900
        # Calculate scale and dims for canvas coordinate reverse-mapping
        scale = min(1.0, MAX_DISPLAY_WIDTH / page_img_np.shape[1])
        disp_w = int(page_img_np.shape[1] * scale)
        disp_h = int(page_img_np.shape[0] * scale)
        
        # Pull pre-cached display image base64 data URI
        disp_img_b64 = st.session_state.page_disp_images[p_idx]
        
        # We strictly bind the Streamlit component key to the current page index.
        # This is absolutely vital because it guarantees the Python widget-cache isolates variables per-page,
        # ensuring that Page 1's unsaved brush strokes resting in the cache don't ghost/bleed into Page 2!
        canvas_key = f"manual_snipper_page_{p_idx}"
        
        # We append dynamic metadata to force Streamlit's JSON comparator to register a change
        # whenever we navigate or undo, which seamlessly triggers a GPU redraw instead of blowing up the component!
        initial_drawing = {
            "version": "4.4.0",
            "objects": st.session_state.page_objects[p_idx],
            "ext_metadata": {"page": p_idx, "v": st.session_state.render_keys[p_idx]},
            "background": "transparent",
            "backgroundImage": {
                "type": "image",
                "version": "4.4.0",
                "src": disp_img_b64,
                "originX": "left",
                "originY": "top",
                "crossOrigin": "anonymous"
            }
        }
        
        canvas_result = st_canvas(
            fill_color="rgba(0, 0, 255, 0.2)", # Blue boxes
            stroke_width=2,
            stroke_color="rgba(0, 0, 255, 1)",
            # WARNING: DO NOT PASS `background_image=` here! Streamlit Cloud heavily glitches with relative media paths.
            update_streamlit=True,
            height=disp_h,
            width=disp_w,
            drawing_mode="rect",
            initial_drawing=initial_drawing,
            key=canvas_key
        )
        
        if canvas_result.json_data is not None:
            # We store the live JSON in a temp var so callbacks trigger securely
            rects = [obj for obj in canvas_result.json_data["objects"] if obj["type"] == "rect"]
            st.session_state.temp_canvas_objects[p_idx] = rects
            
            # Auto-clear redo stack if the canvas detects a brand new drawing (length increases)
            if len(rects) > len(st.session_state.page_objects[p_idx]):
                st.session_state.redo_stack[p_idx] = []

        # Control Row Bottom
        st.write("") # Spacer
        b1, b2, b3, b4, b5, b6 = st.columns([1,1,1,1,1,1])
        b1.button("⬅️ Previous ", on_click=nav_prev, disabled=(p_idx == 0), key="prev_bot")
        b3.button("Next ➡️ ", on_click=nav_next, disabled=(p_idx == total_pages - 1), key="next_bot")
        b4.button("↩️ Undo ", on_click=do_undo, key="undo_bot")
        b5.button("↪️ Redo ", on_click=do_redo, key="redo_bot")
        b6.button("🗑️ Delete All ", on_click=do_clear, key="del_bot")

    with tabs[1]:
        st.subheader("Assemble & Export")
        
        # Ensure the active page is committed before calculation
        commit_canvas_state()
        
        total_snips = sum(len(objs) for objs in st.session_state.page_objects.values())
        st.write(f"Total sections highlighted across all pages: **{total_snips}**")
        
        if total_snips > 0:
            if st.button("Generate Condensed Part PDF", type="primary"):
                with st.spinner("Stitching your highlights together..."):
                    A4_WIDTH = images[0].shape[1]
                    A4_HEIGHT = int(A4_WIDTH * 1.414)
                    MARGIN = 50
                    SPACING = 30
                    
                    pages = []
                    current_page = Image.new('RGB', (A4_WIDTH, A4_HEIGHT), (255, 255, 255))
                    current_y = MARGIN
                    
                    for p_num in sorted(st.session_state.page_objects.keys()):
                        local_scale = min(1.0, MAX_DISPLAY_WIDTH / images[p_num].shape[1])
                        raw_objects = st.session_state.page_objects[p_num]
                        
                        scaled_boxes = []
                        for obj in raw_objects:
                            x = int(obj["left"] / local_scale)
                            y = int(obj["top"] / local_scale)
                            w = int((obj["width"] * obj.get("scaleX", 1)) / local_scale)
                            h = int((obj["height"] * obj.get("scaleY", 1)) / local_scale)
                            scaled_boxes.append((x, y, w, h))
                            
                        # Sort by Y coordinate top-to-bottom to guarantee reading order
                        scaled_boxes = sorted(scaled_boxes, key=lambda b: b[1])
                        
                        for (x, y, w, h) in scaled_boxes:
                            cx, cy = max(0, x), max(0, y)
                            crop_np = images[p_num][cy:cy+h, cx:cx+w]
                            if crop_np.size > 0:
                                crop = Image.fromarray(crop_np)
                                
                                if current_y + crop.height > A4_HEIGHT - MARGIN:
                                    pages.append(current_page)
                                    current_page = Image.new('RGB', (A4_WIDTH, A4_HEIGHT), (255, 255, 255))
                                    current_y = MARGIN
                                    
                                current_page.paste(crop, (MARGIN, current_y))
                                current_y += crop.height + SPACING
                                
                    pages.append(current_page)
                    
                    pdf_bytes = io.BytesIO()
                    pages[0].save(pdf_bytes, format='PDF', save_all=True, append_images=pages[1:])
                    pdf_bytes.seek(0)
                    
                st.download_button("Download Condensed PDF", pdf_bytes, file_name="condensed_music_part.pdf", mime="application/pdf")
        else:
            st.warning("You haven't highlighted anything yet! Go back to Tab 1 to start snipping.")
