"""Panel grafiklari — SVG koordinatalarini serverda hisoblaydi.

Nima uchun JS kutubxona emas: panelning qolgan grafiklari (tushum ustunlari,
donut) ham shu yo'l bilan chizilgan, sahifalar AJAX bilan almashadi va tashqi
skript yuklash shart emas. Django shablonida arifmetika yo'q, shuning uchun
barcha koordinatalar shu yerda tayyorlanadi.
"""

# SVG ichki koordinata tizimi. Ko'rinadigan o'lcham CSS bilan beriladi,
# shuning uchun bu raqamlar faqat nisbatni belgilaydi.
WIDTH = 720
HEIGHT = 220
PAD_LEFT = 46      # Y o'qi yozuvlari uchun
PAD_RIGHT = 12
PAD_TOP = 12
PAD_BOTTOM = 26    # X o'qi yozuvlari uchun

MAX_POINTS = 240   # bundan ko'p nuqta chizilsa ham ko'z ilg'amaydi


def _plot_area():
    return (
        PAD_LEFT,
        PAD_TOP,
        WIDTH - PAD_LEFT - PAD_RIGHT,
        HEIGHT - PAD_TOP - PAD_BOTTOM,
    )


def _downsample(rows, limit=MAX_POINTS):
    """Nuqtalar sonini kamaytiradi, lekin BIRINCHI va OXIRGISI saqlanadi —
    grafikning boshi va oxiri haqiqiy vaqtga to'g'ri kelishi kerak."""
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    picked = [rows[int(i * step)] for i in range(limit)]
    if picked[-1] is not rows[-1]:
        picked[-1] = rows[-1]
    return picked


def line_chart(rows, *, value_getter, unit='', decimals=0):
    """Vaqt o'qidagi chiziqli grafik.

    `rows` — `recorded_at` maydoni bor obyektlar (vaqt bo'yicha tartiblangan).
    `value_getter(row)` qiymatni qaytaradi yoki `None` (o'lchov kelmagan).

    Ikkitadan kam nuqta bo'lsa `None` qaytadi — bitta nuqtadan dinamika
    ko'rinmaydi, shablon esa bo'sh holatni chiqaradi.
    """
    points = [(row.recorded_at, value_getter(row)) for row in rows]
    points = [(at, value) for at, value in points if value is not None]
    if len(points) < 2:
        return None

    points = _downsample(points)

    x0, y0, plot_w, plot_h = _plot_area()
    times = [at for at, _ in points]
    values = [value for _, value in points]

    t_start, t_end = times[0], times[-1]
    span = (t_end - t_start).total_seconds() or 1

    lo, hi = min(values), max(values)
    # Chiziq ramkaga yopishib qolmasligi uchun ustidan/ostidan bo'sh joy.
    # Qiymatlar butunlay o'zgarmasa ham grafik ko'rinishi kerak.
    margin = (hi - lo) * 0.15 or (abs(hi) * 0.02 or 1)
    lo, hi = lo - margin, hi + margin
    scale = hi - lo

    def to_x(at):
        return x0 + (at - t_start).total_seconds() / span * plot_w

    def to_y(value):
        return y0 + plot_h - (value - lo) / scale * plot_h

    coords = [(to_x(at), to_y(value)) for at, value in points]
    polyline = ' '.join(f'{x:.1f},{y:.1f}' for x, y in coords)

    # To'ldirish uchun yopiq kontur: chiziq -> pastki chekka -> boshiga qaytish
    area = (
        f'M {coords[0][0]:.1f},{y0 + plot_h:.1f} '
        + ' '.join(f'L {x:.1f},{y:.1f}' for x, y in coords)
        + f' L {coords[-1][0]:.1f},{y0 + plot_h:.1f} Z'
    )

    def fmt(value):
        return f'{value:.{decimals}f}'

    grid = []
    for i in range(5):
        value = hi - scale * i / 4
        grid.append({
            'y': round(y0 + plot_h * i / 4, 1),
            'label': fmt(value),
        })

    ticks = []
    for i in range(4):
        at = times[0] + (times[-1] - times[0]) * i / 3
        ticks.append({
            'x': round(x0 + plot_w * i / 3, 1),
            'label': at.strftime('%H:%M'),
        })

    average = sum(values) / len(values)
    return {
        'width': WIDTH, 'height': HEIGHT,
        'plot_x': x0, 'plot_y': y0, 'plot_w': plot_w, 'plot_h': plot_h,
        'polyline': polyline,
        'area': area,
        'grid': grid,
        'ticks': ticks,
        'unit': unit,
        'count': len(points),
        'min': fmt(min(values)),
        'max': fmt(max(values)),
        'avg': fmt(average),
        'last': fmt(values[-1]),
    }
