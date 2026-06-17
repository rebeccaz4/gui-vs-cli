"""Offline tests for the new Draw verifier endpoints (no sandbox needed).

Covers:
  - Registry preference parsing (draw-prefs, check-draw-pref, check-registry-key)
  - ODG page property parsing (parse-page-props, check-page-property)
  - Shape hyperlink parsing (parse-shape-hyperlinks, check-shape-hyperlink)
  - PDF outline/page-count parsing (parse-pdf-info, check-pdf-bookmark, check-pdf-page-count)

Run with: python verifiers/libreoffice_draw/test_offline_extensions.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import libreoffice_draw as lod


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

REGISTRY_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry"
           xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <oor:item oor:path="/org.openoffice.Office.Draw/Layout/Other/MeasureUnit">
    <oor:prop oor:name="Metric" oor:op="fuse"><oor:value>8</oor:value></oor:prop>
  </oor:item>
  <oor:item oor:path="/org.openoffice.Office.Draw/Layout/Other">
    <oor:prop oor:name="TabStop" oor:op="fuse"><oor:value>3175</oor:value></oor:prop>
  </oor:item>
  <oor:item oor:path="/org.openoffice.Office.Draw/Snap/Grid/Options">
    <oor:prop oor:name="VisibleGrid" oor:op="fuse"><oor:value>true</oor:value></oor:prop>
    <oor:prop oor:name="SnapToGrid" oor:op="fuse"><oor:value>true</oor:value></oor:prop>
  </oor:item>
  <oor:item oor:path="/org.openoffice.Office.Draw/Snap/Grid/Resolution/XAxis">
    <oor:prop oor:name="Metric" oor:op="fuse"><oor:value>500</oor:value></oor:prop>
  </oor:item>
  <oor:item oor:path="/org.openoffice.Office.Draw/Snap/Grid/Resolution/YAxis">
    <oor:prop oor:name="Metric" oor:op="fuse"><oor:value>500</oor:value></oor:prop>
  </oor:item>
  <oor:item oor:path="/org.openoffice.Office.Draw/Snap/Grid/Subdivision/XAxis">
    <oor:prop oor:name="Count" oor:op="fuse"><oor:value>4</oor:value></oor:prop>
  </oor:item>
  <oor:item oor:path="/org.openoffice.Office.Draw/Snap/Grid/Subdivision/YAxis">
    <oor:prop oor:name="Count" oor:op="fuse"><oor:value>4</oor:value></oor:prop>
  </oor:item>
  <oor:item oor:path="/org.openoffice.Office.Common/Save/Document">
    <oor:prop oor:name="Draw" oor:op="fuse"><oor:value>MS PowerPoint 97</oor:value></oor:prop>
    <oor:prop oor:name="AutoSave" oor:op="fuse"><oor:value>true</oor:value></oor:prop>
    <oor:prop oor:name="AutoSaveTimeIntervall" oor:op="fuse"><oor:value>10</oor:value></oor:prop>
    <oor:prop oor:name="CreateBackup" oor:op="fuse"><oor:value>true</oor:value></oor:prop>
  </oor:item>
</oor:items>
"""


def _build_odg_with_props(path: str, page_width="42cm", page_height="29.7cm",
                          margin="2cm", bg_color="#FFFFCC", page_name="Cover",
                          hyperlink_on_page0: tuple[str, str] | None = None,
                          extra_pages: int = 0):
    """Build a minimal ODG file exercising page properties and shape hyperlinks."""
    # Page layout + master-page + drawing-page style live in styles.xml
    styles_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
    xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
    office:version="1.2">
 <office:styles>
  <style:style style:name="dp1" style:family="drawing-page">
   <style:drawing-page-properties draw:fill="solid" draw:fill-color="{bg_color}"/>
  </style:style>
 </office:styles>
 <office:automatic-styles>
  <style:page-layout style:name="PM0">
   <style:page-layout-properties fo:page-width="{page_width}" fo:page-height="{page_height}"
     fo:margin-top="{margin}" fo:margin-bottom="{margin}" fo:margin-left="{margin}" fo:margin-right="{margin}"/>
  </style:page-layout>
 </office:automatic-styles>
 <office:master-styles>
  <style:master-page style:name="Default" style:page-layout-name="PM0" draw:style-name="dp1"/>
 </office:master-styles>
</office:document-styles>
"""
    page_tail = ""
    for i in range(extra_pages):
        page_tail += f'<draw:page draw:name="Extra{i}" draw:master-page-name="Default"></draw:page>'
    if hyperlink_on_page0:
        href, text = hyperlink_on_page0
        hyperlink_frag = (
            f'<draw:text-box>'
            f'<text:p><text:a xlink:href="{href}" xlink:type="simple">{text}</text:a></text:p>'
            f'</draw:text-box>'
        )
    else:
        hyperlink_frag = ""
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
  xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  office:version="1.2">
  <office:body>
    <office:drawing>
      <draw:page draw:name="{page_name}" draw:master-page-name="Default">
        <draw:rect draw:name="r1" svg:x="2cm" svg:y="2cm" svg:width="3cm" svg:height="2cm">
          <text:p>Hello</text:p>
        </draw:rect>
        {hyperlink_frag}
      </draw:page>
      {page_tail}
    </office:drawing>
  </office:body>
</office:document-content>
"""
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
  <manifest:file-entry manifest:media-type="application/vnd.oasis.opendocument.graphics" manifest:full-path="/"/>
  <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/>
  <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="styles.xml"/>
</manifest:manifest>
"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.graphics",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/manifest.xml", manifest)
        z.writestr("content.xml", content_xml)
        z.writestr("styles.xml", styles_xml)


def _build_mini_pdf(path: str, pages: int = 3,
                    bookmark_titles: list[str] | None = None) -> None:
    """Build a trivial hand-rolled PDF with N pages and optional outline entries."""
    bookmark_titles = bookmark_titles or []
    lines = [b"%PDF-1.4\n"]
    n = 0

    def add(body: bytes) -> int:
        nonlocal n
        n += 1
        lines.append(f"{n} 0 obj".encode() + b"\n" + body + b"\nendobj\n")
        return n

    # Reserve ids
    catalog_id = add(b"<< PLACEHOLDER >>")
    pages_id = add(b"<< PLACEHOLDER >>")
    outlines_id = add(b"<< PLACEHOLDER >>") if bookmark_titles else None
    page_ids: list[int] = []
    for _ in range(pages):
        page_ids.append(add(f"<</Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792]>>".encode()))
    bm_ids: list[int] = []
    for t in bookmark_titles:
        bm_ids.append(add(b""))

    # Fix up bookmark objects (need Prev/Next/Parent)
    fixed = []
    for idx, oid in enumerate(bm_ids):
        title = bookmark_titles[idx].encode()
        parts = [b"/Title (", title, b")", f" /Parent {outlines_id} 0 R".encode()]
        if idx > 0:
            parts.append(f" /Prev {bm_ids[idx-1]} 0 R".encode())
        if idx + 1 < len(bm_ids):
            parts.append(f" /Next {bm_ids[idx+1]} 0 R".encode())
        fixed.append((oid, b"<<" + b"".join(parts) + b">>"))
    # Reconstruct
    out = bytearray()
    out += b"%PDF-1.4\n"
    def write_obj(oid: int, body: bytes) -> None:
        out.extend(f"{oid} 0 obj\n".encode() + body + b"\nendobj\n")
    kids_str = " ".join(f"{i} 0 R" for i in page_ids).encode()
    catalog_body = b"<</Type /Catalog /Pages " + f"{pages_id} 0 R".encode()
    if outlines_id is not None:
        catalog_body += f" /Outlines {outlines_id} 0 R".encode()
    catalog_body += b">>"
    write_obj(catalog_id, catalog_body)
    write_obj(pages_id, f"<</Type /Pages /Count {pages} /Kids [{kids_str.decode()}]>>".encode())
    if outlines_id is not None:
        first = bm_ids[0]
        last = bm_ids[-1]
        write_obj(outlines_id,
                  f"<</Type /Outlines /First {first} 0 R /Last {last} 0 R /Count {len(bm_ids)}>>".encode())
    for oid in page_ids:
        write_obj(oid, f"<</Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792]>>".encode())
    for oid, body in fixed:
        write_obj(oid, body)
    out += b"trailer<</Size 99 /Root " + f"{catalog_id} 0 R".encode() + b">>\n%%EOF\n"
    with open(path, "wb") as f:
        f.write(out)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class DrawPrefsTests(unittest.TestCase):
    def _write_fake_registry(self, tmpdir: str) -> Path:
        p = Path(tmpdir) / ".config" / "libreoffice" / "4" / "user"
        p.mkdir(parents=True, exist_ok=True)
        f = p / "registrymodifications.xcu"
        f.write_text(REGISTRY_XCU)
        return f

    def test_draw_prefs_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_fake_registry(td)
            with mock.patch.object(Path, "home", return_value=Path(td)):
                v = lod.LibreOfficeDrawVerifier()
                prefs = v.get_draw_prefs()
                self.assertIsNone(prefs.get("error"))
                self.assertEqual(prefs["measurement_unit_draw"], "8")
                self.assertEqual(prefs["default_tab_stop_draw"], "3175")
                self.assertEqual(prefs["default_save_filter_draw"], "MS PowerPoint 97")
                self.assertEqual(prefs["autosave_enabled"], "true")
                self.assertEqual(prefs["autosave_interval"], "10")
                self.assertEqual(prefs["backup_enabled"], "true")
                self.assertEqual(prefs["grid_visible_draw"], "true")
                self.assertEqual(prefs["snap_to_grid_draw"], "true")
                self.assertEqual(prefs["grid_resolution_x"], "500")
                self.assertEqual(prefs["grid_resolution_y"], "500")
                self.assertEqual(prefs["grid_subdivision_x"], "4")
                self.assertEqual(prefs["grid_subdivision_y"], "4")

    def test_check_draw_pref_positive_and_negative(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_fake_registry(td)
            with mock.patch.object(Path, "home", return_value=Path(td)):
                v = lod.LibreOfficeDrawVerifier()
                self.assertTrue(v.check_draw_pref("measurement_unit_draw", "8")["match"])
                self.assertFalse(v.check_draw_pref("measurement_unit_draw", "2")["match"])
                # Substring match for filter
                self.assertTrue(v.check_draw_pref("default_save_filter_draw", "PowerPoint")["match"])
                self.assertFalse(v.check_draw_pref("default_save_filter_draw", "Calc")["match"])

    def test_check_registry_key_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_fake_registry(td)
            with mock.patch.object(Path, "home", return_value=Path(td)):
                v = lod.LibreOfficeDrawVerifier()
                r = v.check_registry_key("Snap/Grid/Options", "SnapToGrid", "true")
                self.assertTrue(r["match"])
                r = v.check_registry_key("Snap/Grid/Options", "SnapToGrid", "false")
                self.assertFalse(r["match"])

    def test_missing_registry(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(Path, "home", return_value=Path(td)):
                v = lod.LibreOfficeDrawVerifier()
                r = v.get_draw_prefs()
                self.assertIn("error", r)


class PagePropsTests(unittest.TestCase):
    def test_parse_page_props_a3_landscape(self):
        v = lod.LibreOfficeDrawVerifier()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "t.odg")
            _build_odg_with_props(path, page_width="42cm", page_height="29.7cm",
                                  margin="2cm", bg_color="#FFFFCC", page_name="Cover")
            info = v.parse_file_page_properties(path)
            self.assertEqual(info["count"], 1)
            page = info["pages"][0]
            self.assertEqual(page["name"], "Cover")
            self.assertAlmostEqual(page["width_cm"], 42.0, delta=0.05)
            self.assertAlmostEqual(page["height_cm"], 29.7, delta=0.05)
            self.assertAlmostEqual(page["margin_top_cm"], 2.0, delta=0.05)
            self.assertEqual(page["background_fill_color"], "#FFFFCC")

            # check-page-property cases
            self.assertTrue(v.check_page_property(0, "name", "Cover", file_path=path)["match"])
            self.assertFalse(v.check_page_property(0, "name", "Draft", file_path=path)["match"])
            self.assertTrue(v.check_page_property(0, "width_cm", "42", file_path=path)["match"])
            self.assertTrue(v.check_page_property(0, "background_fill_color",
                                                  "FFFFCC", file_path=path)["match"])
            self.assertFalse(v.check_page_property(0, "background_fill_color",
                                                   "000000", file_path=path)["match"])


class ShapeHyperlinkTests(unittest.TestCase):
    def test_shape_hyperlink_detection(self):
        v = lod.LibreOfficeDrawVerifier()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "t.odg")
            _build_odg_with_props(path, hyperlink_on_page0=("#Intro", "Go to Intro"),
                                  extra_pages=1)
            info = v.parse_file_shape_hyperlinks(0, path)
            self.assertEqual(info["count"], 1)
            self.assertEqual(info["links"][0]["href"], "#Intro")
            self.assertEqual(info["links"][0]["text"], "Go to Intro")

            self.assertTrue(v.check_shape_hyperlink(0, "#Intro", file_path=path)["exists"])
            self.assertTrue(v.check_shape_hyperlink(0, "Intro", "Go to", file_path=path)["exists"])
            self.assertFalse(v.check_shape_hyperlink(0, "Methods", file_path=path)["exists"])
            # Page 1 has no links
            self.assertFalse(v.check_shape_hyperlink(1, "Intro", file_path=path)["exists"])


class PdfTests(unittest.TestCase):
    def test_pdf_basic(self):
        v = lod.LibreOfficeDrawVerifier()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "t.pdf")
            _build_mini_pdf(path, pages=3, bookmark_titles=["Overview", "Architecture", "Roadmap"])
            info = v.parse_pdf_info(path)
            self.assertEqual(info["page_count"], 3)
            self.assertIn("Overview", info["bookmarks"])
            self.assertIn("Roadmap", info["bookmarks"])

            self.assertTrue(v.check_pdf_page_count(path, 3)["match"])
            self.assertFalse(v.check_pdf_page_count(path, 5)["match"])
            self.assertTrue(v.check_pdf_bookmark(path, "Architecture")["exists"])
            self.assertFalse(v.check_pdf_bookmark(path, "Missing")["exists"])

    def test_pdf_missing(self):
        v = lod.LibreOfficeDrawVerifier()
        r = v.parse_pdf_info("/tmp/does-not-exist.pdf")
        self.assertIn("error", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
