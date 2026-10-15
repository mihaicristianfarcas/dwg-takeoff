"""Project information: notes and reference documents (PDF / DXF / text) reach the AI prompt."""

import ezdxf
import pytest

from dwg_takeoff.ai.request import PlanRequest
from dwg_takeoff.project_info import ProjectInfo, extract_text


def make_pdf(path, lines):
    from matplotlib.backends.backend_pdf import FigureCanvasPdf
    from matplotlib.figure import Figure

    fig = Figure(figsize=(8.27, 11.69))
    FigureCanvasPdf(fig)
    for i, line in enumerate(lines):
        fig.text(0.08, 0.92 - i * 0.04, line, fontsize=11)
    fig.savefig(path)


def test_pdf_text(tmp_path):
    pdf = tmp_path / "detaliu.pdf"
    make_pdf(pdf, ["DETALIU SISTEM RUTIER SR1", "Pavele beton 8 cm", "Beton C25/30 20 cm"])
    text = extract_text(pdf)
    assert "SR1" in text and "20 cm" in text


def test_dxf_detail_text(tmp_path):
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_text("Placa pe sol 18 cm", height=2.5).set_placement((0, 10))
    msp.add_text("Fundatie continua 60x120", height=2.5).set_placement((0, 0))
    msp.add_line((0, -5), (50, -5))
    path = tmp_path / "fundatii.dxf"
    doc.saveas(path)
    text = extract_text(path)
    assert "Placa pe sol 18 cm" in text and "60x120" in text


def test_project_info_prompt(tmp_path):
    pi = ProjectInfo(tmp_path)
    assert pi.prompt_text() == ""
    pi.set_notes("Placa parter: 18 cm")
    item = pi.add("caiet.txt", b"Strat beton drumuri: 20 cm")
    with pytest.raises(ValueError):
        pi.add("poza.jpg", b"x")
    text = pi.prompt_text()
    assert "18 cm" in text and "caiet.txt" in text and "20 cm" in text
    req = PlanRequest(
        query="beton pe drumuri",
        drawing=None,
        digest={},
        digest_text="",
        region=None,
        table_transform=None,
        run_dir=tmp_path,
        project_info=text,
    )
    rt = req.request_text()
    assert rt.index("PROJECT INFORMATION") < rt.index("CLIENT REQUEST") and rt.endswith("beton pe drumuri")
    pi.remove(item["id"])
    assert pi.documents() == [] and "20 cm" not in pi.prompt_text()
