from pathlib import Path
import random
from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(__file__).parent / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)


INK = "#1F2937"
MUTED = "#6B7280"
GRID = "#E5E7EB"
BLUE = "#2F80ED"
ORANGE = "#F59E0B"
GREEN = "#10B981"
RED = "#EF4444"
PURPLE = "#8B5CF6"
TEAL = "#14B8A6"
GRAY = "#9CA3AF"
LIGHT_BLUE = "#EAF2FF"
LIGHT_ORANGE = "#FFF7E6"
LIGHT_GREEN = "#ECFDF5"
LIGHT_RED = "#FEF2F2"
LIGHT_PURPLE = "#F3E8FF"
LIGHT_GRAY = "#F3F4F6"


def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


FONT_TITLE = font(38, True)
FONT_H2 = font(27, True)
FONT_BODY = font(22)
FONT_SMALL = font(18)
FONT_TINY = font(15)
FONT_NUM = font(19, True)


def draw_round_box(
    draw, xy, text, fill, outline, radius=18, title_font=FONT_BODY, text_fill=INK
):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=3)
    lines = wrap_text(draw, text, title_font, x2 - x1 - 34)
    total_h = len(lines) * 28
    y = y1 + ((y2 - y1) - total_h) / 2
    for line in lines:
        w = draw.textbbox((0, 0), line, font=title_font)[2]
        draw.text((x1 + (x2 - x1 - w) / 2, y), line, font=title_font, fill=text_fill)
        y += 28


def wrap_text(draw, text, fnt, max_width):
    words = text.split()
    lines = []
    cur = ""
    for word in words:
        trial = (cur + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=fnt)[2] <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def arrow(draw, start, end, color=INK, width=4, head=16):
    draw.line([start, end], fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    p1 = (x2 - head * ux + head * 0.55 * px, y2 - head * uy + head * 0.55 * py)
    p2 = (x2 - head * ux - head * 0.55 * px, y2 - head * uy - head * 0.55 * py)
    draw.polygon([end, p1, p2], fill=color)


def poly_arrow(draw, points, color=INK, width=4, head=16):
    if len(points) < 2:
        return
    for a, b in zip(points[:-2], points[1:-1]):
        draw.line([a, b], fill=color, width=width)
    arrow(draw, points[-2], points[-1], color=color, width=width, head=head)


def jitter_point(point, amount):
    x, y = point
    return (x + random.uniform(-amount, amount), y + random.uniform(-amount, amount))


def sketch_line(draw, start, end, color=INK, width=3, passes=2, jitter=2.6):
    for _ in range(passes):
        draw.line(
            [jitter_point(start, jitter), jitter_point(end, jitter)],
            fill=color,
            width=width,
        )


def sketch_polyline(draw, points, color=INK, width=3, passes=2, jitter=2.6):
    for _ in range(passes):
        jittered = [jitter_point(p, jitter) for p in points]
        draw.line(jittered, fill=color, width=width, joint="curve")


def sketch_arrow(draw, start, end, color=INK, width=3, head=18):
    sketch_line(draw, start, end, color=color, width=width, passes=2, jitter=2.4)
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    p1 = (x2 - head * ux + head * 0.55 * px, y2 - head * uy + head * 0.55 * py)
    p2 = (x2 - head * ux - head * 0.55 * px, y2 - head * uy - head * 0.55 * py)
    for _ in range(2):
        draw.line(
            [jitter_point(p1, 1.8), jitter_point(end, 1.8), jitter_point(p2, 1.8)],
            fill=color,
            width=width,
        )


def sketch_poly_arrow(draw, points, color=INK, width=3, head=18):
    if len(points) < 2:
        return
    sketch_polyline(draw, points, color=color, width=width, passes=2, jitter=2.2)
    sketch_arrow(draw, points[-2], points[-1], color=color, width=width, head=head)


def draw_sketch_box(
    draw, xy, text, fill, outline, title_font=FONT_BODY, text_fill=INK, radius=16
):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=None)
    for _ in range(3):
        off = random.uniform(-2.2, 2.2)
        draw.rounded_rectangle(
            (
                x1 + off,
                y1 - off,
                x2 + random.uniform(-2, 2),
                y2 + random.uniform(-2, 2),
            ),
            radius=radius + random.uniform(-3, 3),
            outline=outline,
            width=3,
        )
    lines = wrap_text(draw, text, title_font, x2 - x1 - 30)
    line_gap = 27 if title_font == FONT_BODY else 31
    total_h = len(lines) * line_gap
    y = y1 + ((y2 - y1) - total_h) / 2
    for line in lines:
        w = draw.textbbox((0, 0), line, font=title_font)[2]
        draw.text(
            (x1 + (x2 - x1 - w) / 2, y), font=title_font, text=line, fill=text_fill
        )
        y += line_gap


def draw_arrow_legend(draw, items, x, y):
    draw.text((x, y + 3), "Arrow legend:", font=FONT_TINY, fill=MUTED)
    cursor = x + 130
    for color, label in items:
        sketch_arrow(
            draw, (cursor, y + 14), (cursor + 42, y + 14), color=color, width=3, head=10
        )
        draw.text((cursor + 54, y), label, font=FONT_TINY, fill=INK)
        cursor += 54 + draw.textbbox((0, 0), label, font=FONT_TINY)[2] + 30


def draw_system_overview():
    random.seed(17)
    img = Image.new("RGB", (1800, 950), "white")
    d = ImageDraw.Draw(img)

    d.text(
        (72, 44),
        "Artifact-aware Teacher-Student-Judge optimization loop",
        font=FONT_TITLE,
        fill=INK,
    )
    d.text(
        (74, 92),
        "Execution evidence is converted into failure feedback; only SKILL.md is rewritten.",
        font=FONT_BODY,
        fill=MUTED,
    )

    # Excalidraw-like soft panels.
    d.rounded_rectangle((62, 155, 1738, 590), radius=30, fill="#FBFCFE", outline=None)
    d.rounded_rectangle((62, 620, 1738, 850), radius=30, fill="#FAFAFB", outline=None)
    for _ in range(2):
        d.rounded_rectangle(
            (
                62 + random.uniform(-2, 2),
                155 + random.uniform(-2, 2),
                1738 + random.uniform(-2, 2),
                590 + random.uniform(-2, 2),
            ),
            radius=30,
            outline="#E7ECF3",
            width=3,
        )
        d.rounded_rectangle(
            (
                62 + random.uniform(-2, 2),
                620 + random.uniform(-2, 2),
                1738 + random.uniform(-2, 2),
                850 + random.uniform(-2, 2),
            ),
            radius=30,
            outline="#E7ECF3",
            width=3,
        )
    d.text((92, 172), "1. Execute and score artifacts", font=FONT_SMALL, fill=MUTED)
    d.text(
        (415, 637), "2. Rewrite skill document with gates", font=FONT_SMALL, fill=MUTED
    )

    boxes = {
        "inputs": (105, 230, 355, 335),
        "skill": (105, 405, 355, 510),
        "student": (455, 300, 725, 460),
        "artifact": (815, 300, 1095, 460),
        "evidence": (1190, 220, 1490, 345),
        "judge": (1190, 415, 1490, 555),
        "rubric": (1535, 415, 1710, 555),
        "teacher": (815, 680, 1095, 820),
        "gate": (455, 680, 725, 820),
        "next_skill": (105, 680, 355, 820),
        "best": (1190, 680, 1490, 820),
    }

    draw_sketch_box(
        d,
        boxes["inputs"],
        "Test cases + fixtures",
        LIGHT_GRAY,
        GRAY,
        title_font=FONT_BODY,
    )
    draw_sketch_box(
        d,
        boxes["skill"],
        "Current SKILL.md\nM_r",
        LIGHT_BLUE,
        BLUE,
        title_font=FONT_BODY,
    )
    draw_sketch_box(
        d,
        boxes["student"],
        "Student\nfrozen SLM",
        LIGHT_GREEN,
        GREEN,
        title_font=FONT_H2,
    )
    draw_sketch_box(
        d,
        boxes["artifact"],
        "Output artifact\nDOCX / GIF / text",
        LIGHT_ORANGE,
        ORANGE,
        title_font=FONT_BODY,
    )
    draw_sketch_box(
        d,
        boxes["evidence"],
        "Artifact evidence\nrendered pages,\nmetadata",
        LIGHT_GRAY,
        GRAY,
        title_font=FONT_BODY,
    )
    draw_sketch_box(
        d, boxes["rubric"], "Rubric\ncache", LIGHT_PURPLE, PURPLE, title_font=FONT_BODY
    )
    draw_sketch_box(
        d,
        boxes["judge"],
        "Judge\nscore + failure summary",
        LIGHT_RED,
        RED,
        title_font=FONT_BODY,
    )
    draw_sketch_box(
        d,
        boxes["teacher"],
        "Teacher\nrewrite SKILL.md",
        LIGHT_BLUE,
        BLUE,
        title_font=FONT_BODY,
    )
    draw_sketch_box(
        d,
        boxes["gate"],
        "Validation gates\naccept, reject,\nrollback",
        "#FFF1F2",
        RED,
        title_font=FONT_BODY,
    )
    draw_sketch_box(
        d,
        boxes["next_skill"],
        "Accepted next skill\nM_{r+1}",
        LIGHT_BLUE,
        BLUE,
        title_font=FONT_BODY,
    )
    draw_sketch_box(
        d,
        boxes["best"],
        "Best snapshot\nR_peak",
        LIGHT_GREEN,
        GREEN,
        title_font=FONT_BODY,
    )

    # Main execution path.
    sketch_arrow(d, (355, 282), (455, 355), MUTED)
    sketch_arrow(d, (355, 458), (455, 405), BLUE)
    sketch_arrow(d, (725, 380), (815, 380), GREEN)
    sketch_arrow(d, (1095, 352), (1190, 285), ORANGE)
    sketch_arrow(d, (1340, 345), (1340, 415), ORANGE)
    sketch_arrow(d, (1535, 485), (1490, 485), PURPLE)

    # Feedback, rewrite, and version-selection path. Routed below the scoring lane to avoid crossings.
    sketch_poly_arrow(d, [(1190, 510), (1135, 510), (1135, 750), (1095, 750)], RED)
    sketch_arrow(d, (815, 750), (725, 750), BLUE)
    sketch_arrow(d, (455, 750), (355, 750), BLUE)
    sketch_poly_arrow(d, [(230, 680), (230, 595), (230, 510)], BLUE)
    sketch_arrow(d, (1340, 555), (1340, 680), GREEN)

    # Keep text off the arrows. The color legend explains edge semantics without
    # cluttering the main flow.
    draw_arrow_legend(
        d,
        [
            (GRAY, "task prompt"),
            (BLUE, "skill context / rewrite"),
            (GREEN, "execution / selection"),
            (ORANGE, "artifact evidence"),
            (PURPLE, "stable rubric"),
            (RED, "failure feedback"),
        ],
        92,
        856,
    )

    d.rounded_rectangle((72, 890, 1728, 935), radius=14, fill="#F9FAFB", outline=None)
    for _ in range(2):
        d.rounded_rectangle(
            (
                72 + random.uniform(-2, 2),
                890 + random.uniform(-2, 2),
                1728 + random.uniform(-2, 2),
                935 + random.uniform(-2, 2),
            ),
            radius=14,
            outline=GRID,
            width=2,
        )
    d.text(
        (100, 900),
        "Key design choice: optimize the skill document, not the Student weights or per-task outputs.",
        font=FONT_BODY,
        fill=INK,
    )

    img.save(OUT_DIR / "fig1_system_overview.png", dpi=(200, 200))


def draw_results_chart():
    img = Image.new("RGB", (1800, 1050), "white")
    d = ImageDraw.Draw(img)

    d.text(
        (80, 48),
        "No-Skill vs original skill vs optimized skill",
        font=FONT_TITLE,
        fill=INK,
    )
    d.text(
        (82, 97),
        "R_peak is the best skill version retained during optimization; higher score is better.",
        font=FONT_BODY,
        fill=MUTED,
    )

    data = [
        ("docx", 0.891, 0.793, 0.921),
        ("internal-comms", 0.814, 0.735, 0.823),
        ("slack-gif-creator", 0.614, 0.716, 0.886),
    ]
    series = [("No-Skill", GRAY), ("R1 original", BLUE), ("R_peak optimized", ORANGE)]

    left, top, right, bottom = 155, 185, 1650, 830
    ymin, ymax = 0.50, 1.00

    # Grid and axes.
    for tick in [0.50, 0.60, 0.70, 0.80, 0.90, 1.00]:
        y = bottom - (tick - ymin) / (ymax - ymin) * (bottom - top)
        d.line([(left, y), (right, y)], fill=GRID, width=2)
        label = f"{tick:.2f}"
        d.text((88, y - 11), label, font=FONT_SMALL, fill=MUTED)
    d.line([(left, bottom), (right, bottom)], fill=INK, width=3)
    d.line([(left, top), (left, bottom)], fill=INK, width=3)
    d.text((50, 150), "Score", font=FONT_SMALL, fill=MUTED)

    group_w = (right - left) / len(data)
    bar_w = 94
    gap = 18
    for i, (skill, no_skill, r1, rpeak) in enumerate(data):
        cx = left + group_w * (i + 0.5)
        values = [no_skill, r1, rpeak]
        start_x = cx - (3 * bar_w + 2 * gap) / 2
        for j, value in enumerate(values):
            x1 = start_x + j * (bar_w + gap)
            x2 = x1 + bar_w
            y = bottom - (value - ymin) / (ymax - ymin) * (bottom - top)
            fill = series[j][1]
            d.rounded_rectangle((x1, y, x2, bottom), radius=10, fill=fill)
            label = f"{value:.3f}"
            tw = d.textbbox((0, 0), label, font=FONT_NUM)[2]
            d.text((x1 + (bar_w - tw) / 2, y - 30), label, font=FONT_NUM, fill=INK)
        tw = d.textbbox((0, 0), skill, font=FONT_BODY)[2]
        d.text((cx - tw / 2, bottom + 28), skill, font=FONT_BODY, fill=INK)

        delta = rpeak - r1
        delta_text = f"+{delta:.3f}"
        d.rounded_rectangle(
            (cx - 68, top + 18, cx + 68, top + 58),
            radius=20,
            fill=LIGHT_GREEN,
            outline=GREEN,
            width=2,
        )
        tw = d.textbbox((0, 0), delta_text, font=FONT_SMALL)[2]
        d.text((cx - tw / 2, top + 27), delta_text, font=FONT_SMALL, fill=GREEN)

    # Legend.
    lx, ly = 1110, 58
    for name, color in series:
        d.rounded_rectangle((lx, ly, lx + 30, ly + 30), radius=6, fill=color)
        d.text((lx + 42, ly + 3), name, font=FONT_SMALL, fill=INK)
        lx += 230

    # Short interpretation callout.
    d.rounded_rectangle(
        (210, 910, 1590, 990), radius=18, fill="#F9FAFB", outline=GRID, width=2
    )
    d.text(
        (245, 927),
        "Finding: the original skill can hurt a small model (docx, internal-comms), while the optimized skill is best in all three studied skills.",
        font=FONT_BODY,
        fill=INK,
    )

    img.save(OUT_DIR / "fig2_baseline_results.png", dpi=(200, 200))


def draw_learning_curves():
    random.seed(42)
    img = Image.new("RGB", (1800, 1000), "white")
    d = ImageDraw.Draw(img)

    d.text(
        (80, 48),
        "Performance Trajectories over Optimization Rounds",
        font=FONT_TITLE,
        fill=INK,
    )
    d.text(
        (82, 97),
        "Scores represent mean LLM-as-Judge performance over all test cases in each round.",
        font=FONT_BODY,
        fill=MUTED,
    )

    left, top, right, bottom = 150, 180, 1650, 800
    ymin, ymax = 0.50, 1.00

    # Grid and axes (Y-axis)
    for tick in [0.50, 0.60, 0.70, 0.80, 0.90, 1.00]:
        y = bottom - (tick - ymin) / (ymax - ymin) * (bottom - top)
        d.line([(left, y), (right, y)], fill=GRID, width=2)
        label = f"{tick:.2f}"
        d.text((88, y - 11), label, font=FONT_SMALL, fill=MUTED)

    d.line([(left, bottom), (right, bottom)], fill=INK, width=3)
    d.line([(left, top), (left, bottom)], fill=INK, width=3)
    d.text((50, 150), "Score", font=FONT_SMALL, fill=MUTED)
    d.text((right - 50, bottom + 45), "Round", font=FONT_SMALL, fill=MUTED)

    # X-axis ticks
    for r in range(1, 11):
        x = left + (r - 1) / (10 - 1) * (right - left)
        d.line([(x, bottom), (x, bottom + 8)], fill=INK, width=2)
        d.text((x - 8, bottom + 15), f"R{r}", font=FONT_SMALL, fill=INK)

    # Series data comes from distillation_v2/results/stable/*/summary.json.
    docx_scores = [0.793, 0.841, 0.849, 0.903, 0.921, 0.897, 0.921, 0.877]
    internal_scores = [0.735, 0.812, 0.823, 0.792, 0.819, 0.816, 0.810, 0.822]
    slack_scores = [
        0.716,
        0.780,
        0.764,
        0.867,
        0.865,
        0.819,
        0.779,
        0.824,
        0.886,
        0.865,
    ]

    series = [
        ("docx", docx_scores, BLUE),
        ("internal-comms", internal_scores, TEAL),
        ("slack-gif-creator", slack_scores, ORANGE),
    ]

    for name, scores, color in series:
        points = []
        for r_idx, s in enumerate(scores):
            r = r_idx + 1
            x = left + (r - 1) / (10 - 1) * (right - left)
            y = bottom - (s - ymin) / (ymax - ymin) * (bottom - top)
            points.append((x, y))

        # Draw sketch polyline for the curves
        sketch_polyline(d, points, color=color, width=4, passes=3, jitter=1.8)

        # Draw dots and score text for each point
        for r_idx, (x, y) in enumerate(points):
            s = scores[r_idx]
            # Draw dot
            d.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline=INK, width=2)
            # Label peaks and endpoints
            is_peak = s == max(scores)
            is_end = r_idx == len(scores) - 1
            is_start = r_idx == 0
            if is_peak:
                # Star shape or big marker
                d.polygon(
                    [
                        (x, y - 12),
                        (x + 3, y - 3),
                        (x + 12, y - 3),
                        (x + 5, y + 3),
                        (x + 8, y + 12),
                        (x, y + 6),
                        (x - 8, y + 12),
                        (x - 5, y + 3),
                        (x - 12, y - 3),
                        (x - 3, y - 3),
                    ],
                    fill="#F59E0B",
                    outline=INK,
                    width=2,
                )
                if name == "internal-comms":
                    label_x, label_y = x - 64, y + 24
                else:
                    label_x, label_y = x - 34, y - 34
                d.text((label_x, label_y), f"{s:.3f} (Peak)", font=FONT_NUM, fill=INK)
            elif is_end or is_start:
                if name == "docx":
                    label_y = y + 12
                elif name == "internal-comms":
                    label_y = y + 12 if is_end else y - 30
                else:
                    label_y = y - 30
                d.text((x - 20, label_y), f"{s:.3f}", font=FONT_SMALL, fill=INK)

    # Legend
    lx, ly = 1040, 58
    for name, color in [
        ("docx", BLUE),
        ("internal-comms", TEAL),
        ("slack-gif-creator", ORANGE),
    ]:
        # Draw line segment
        d.line([(lx, ly + 15), (lx + 40, ly + 15)], fill=color, width=4)
        d.ellipse(
            (lx + 20 - 5, ly + 15 - 5, lx + 20 + 5, ly + 15 + 5),
            fill=color,
            outline=INK,
            width=1,
        )
        d.text((lx + 55, ly + 3), name, font=FONT_SMALL, fill=INK)
        lx += 220 if name != "internal-comms" else 300

    # Short interpretation callout
    d.rounded_rectangle(
        (150, 880, 1650, 960), radius=18, fill="#F9FAFB", outline=GRID, width=2
    )
    d.text(
        (185, 897),
        "Observation: all three skills peak before the final round or plateau late, supporting early stopping over blindly deploying the last rewrite.",
        font=FONT_BODY,
        fill=INK,
    )

    img.save(OUT_DIR / "fig3_learning_curves.png", dpi=(200, 200))


if __name__ == "__main__":
    draw_system_overview()
    draw_results_chart()
    draw_learning_curves()
    print(f"Wrote figures to {OUT_DIR}")
