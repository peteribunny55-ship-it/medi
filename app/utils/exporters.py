from __future__ import annotations

import io
from typing import Any, Optional

import pandas as pd
import streamlit as st


def _df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()


def csv_download(df: pd.DataFrame, filename: str, label: str = "📥 Download CSV", key: Optional[str] = None) -> None:
    if df is None or len(df) == 0:
        st.info("No data to export.")
        return
    data = _df_to_csv_bytes(df)
    st.download_button(
        label=label,
        data=data,
        file_name=filename,
        mime="text/csv",
        key=key,
    )
    st.caption(f"Rows: {len(df)} — columns: {', '.join(df.columns)}")


def export_dashboard_pdf(conn, user) -> Optional[bytes]:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except Exception:
        return None
    try:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, title="Hospital Ops Dashboard")
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("title", parent=styles["Heading1"], textColor=colors.HexColor("#0B2545"))
        disclaimer_style = ParagraphStyle("disc", parent=styles["BodyText"], textColor=colors.HexColor("#78350F"), backColor=colors.HexColor("#FFFBEB"), borderPadding=6)
        story = []
        story.append(Paragraph("🏥 Hospital Resource Optimization — Dashboard Summary", title_style))
        story.append(Paragraph(f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')} &nbsp;&nbsp; User: {user.get('full_name','')} ({user.get('role','')})", styles["BodyText"]))
        story.append(Spacer(1, 14))

        try:
            from app.core import beds, appointments, queue, inventory, emergency
            beds_cap = beds.utilization_summary(conn)
            total_beds = int(beds_cap.get("total_beds", 0))
            occ = int(beds_cap.get("occupied", 0))
            avail = total_beds - occ
            today = pd.Timestamp.now().strftime("%Y-%m-%d")
            today_appts = len(appointments.list_by_date(conn, today))
            waiting = len(queue.list_tokens(conn, status="Waiting"))
            low_stock = len(inventory.scan_low_stock(conn))
            em = emergency.live_capacity(conn)
            data = [
                ["Metric", "Value"],
                ["Total Beds", str(total_beds)],
                ["Occupied / Available", f"{occ} / {avail}"],
                ["Today's Appointments", str(today_appts)],
                ["Queue Waiting", str(waiting)],
                ["Low-Stock Items", str(low_stock)],
                ["Active Emergencies", str(em.get("active_emergencies", 0))],
            ]
            t = Table(data, hAlign="LEFT", colWidths=[260, 180])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#13315C")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F9FC")]),
            ]))
            story.append(t)
        except Exception as e:
            story.append(Paragraph(f"<i>Could not populate summary: {e}</i>", styles["BodyText"]))
        story.append(Spacer(1, 20))
        story.append(Paragraph("<i>End of prototype PDF summary</i>", styles["Italic"]))
        doc.build(story)
        return buf.getvalue()
    except Exception:
        return None
