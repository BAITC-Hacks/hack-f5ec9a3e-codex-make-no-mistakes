"""Stream OOXML evidence without rounding numeric XML lexemes through binary floats."""

import posixpath
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl.formula.translate import Translator
from openpyxl.styles.numbers import BUILTIN_FORMATS
from openpyxl.utils.cell import range_boundaries

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


@dataclass
class Sheet:
    name: str
    path: str
    position: int
    rows: int
    columns: int
    layout: dict


class Workbook:
    def __init__(self, content: bytes):
        self.archive = ZipFile(BytesIO(content))
        self.strings = []
        if "xl/sharedStrings.xml" in self.archive.namelist():
            with self.archive.open("xl/sharedStrings.xml") as stream:
                for _, node in ET.iterparse(stream):
                    if node.tag == NS + "si":
                        self.strings.append("".join(t.text or "" for t in node.iter(NS + "t")))
                        node.clear()
        self.formats = ["General"]
        if "xl/styles.xml" in self.archive.namelist():
            styles = ET.fromstring(self.archive.read("xl/styles.xml"))
            custom = {
                int(n.attrib["numFmtId"]): n.attrib["formatCode"]
                for n in styles.findall(f"{NS}numFmts/{NS}numFmt")
            }
            self.formats = [
                custom.get(
                    int(n.get("numFmtId", 0)), BUILTIN_FORMATS.get(int(n.get("numFmtId", 0)), "General")
                )
                for n in styles.findall(f"{NS}cellXfs/{NS}xf")
            ]
        relationships = ET.fromstring(self.archive.read("xl/_rels/workbook.xml.rels"))
        targets = {n.attrib["Id"]: n.attrib["Target"] for n in relationships}
        book = ET.fromstring(self.archive.read("xl/workbook.xml"))
        properties = book.find(NS + "workbookPr")
        self.date1904 = properties is not None and properties.get("date1904") in ("1", "true")
        self.sheets = []
        for position, node in enumerate(book.findall(f"{NS}sheets/{NS}sheet")):
            target = targets[node.attrib[REL + "id"]]
            path = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            layout = {
                "state": node.get("state", "visible"),
                "date1904": self.date1904,
                "merged_ranges": [],
                "columns": [],
                "special_rows": [],
            }
            rows = columns = 0
            with self.archive.open(path) as stream:
                for _, element in ET.iterparse(stream):
                    tag = element.tag.removeprefix(NS)
                    if tag == "dimension":
                        _, _, columns, rows = range_boundaries(element.attrib["ref"])
                    elif tag == "mergeCell":
                        layout["merged_ranges"].append(element.attrib["ref"])
                    elif tag == "col":
                        layout["columns"].append(dict(element.attrib))
                    elif tag == "row":
                        if any(k in element.attrib for k in ("hidden", "ht", "outlineLevel")):
                            layout["special_rows"].append(dict(element.attrib))
                    element.clear()
            self.sheets.append(Sheet(node.attrib["name"], path, position, rows, columns, layout))

    def close(self):
        self.archive.close()

    def rows(self, sheet: Sheet):
        shared = {}
        with self.archive.open(sheet.path) as stream:
            # Clear each completed row and sheetData children, keeping memory bounded by a row.
            parent = None
            for event, node in ET.iterparse(stream, events=("start", "end")):
                if event == "start" and node.tag == NS + "sheetData":
                    parent = node
                if event != "end" or node.tag != NS + "row":
                    continue
                cells = {}
                for cell in node.findall(NS + "c"):
                    address = cell.attrib["r"]
                    column = address.rstrip("0123456789")
                    kind = cell.get("t", "n")
                    value = cell.findtext(NS + "v")
                    if value == "" and kind not in ("str", "inlineStr"):
                        value = None
                    inline = cell.find(NS + "is")
                    formula_node = cell.find(NS + "f")
                    if kind == "s" and value is not None:
                        value = self.strings[int(value)]
                        kind = "s"
                    elif inline is not None:
                        value = "".join(t.text or "" for t in inline.iter(NS + "t"))
                        kind = "s"
                    elif kind == "b" and value is not None:
                        value = value == "1"
                    if value is None and formula_node is None:
                        continue
                    data = {
                        "type": kind,
                        "value": value,
                        "number_format": self.formats[int(cell.get("s", 0))],
                    }
                    if formula_node is not None:
                        formula = formula_node.text
                        attrs = dict(formula_node.attrib)
                        if attrs.get("t") == "shared":
                            key = attrs["si"]
                            if formula is not None:
                                shared[key] = (address, "=" + formula)
                            else:
                                origin, source = shared[key]
                                formula = Translator(source, origin=origin).translate_formula(address)[1:]
                        data.update(
                            type="f",
                            formula="=" + formula if formula else None,
                            formula_attributes=attrs,
                            cached_type=kind,
                            cached_value=value,
                        )
                    cells[column] = data
                if cells:
                    yield int(node.attrib["r"]), cells
                node.clear()
                if parent is not None:
                    parent.clear()
