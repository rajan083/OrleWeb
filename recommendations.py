# recommendations.py
#
# Rule-based scoring: given a user's profile, score every product on how
# well it matches body type, occasion, and color theory. Higher = better fit.

COLOR_HARMONY = {
    # (skin_tone, undertone) -> set of colors that flatter
    ('fair', 'cool'):    {'navy', 'burgundy', 'emerald', 'charcoal', 'plum', 'ice_blue'},
    ('fair', 'warm'):    {'olive', 'camel', 'rust', 'cream', 'warm_grey'},
    ('light', 'cool'):   {'navy', 'burgundy', 'grey', 'cobalt', 'plum'},
    ('light', 'warm'):   {'olive', 'tan', 'terracotta', 'mustard', 'cream'},
    ('medium', 'cool'):  {'navy', 'emerald', 'burgundy', 'charcoal', 'royal_blue'},
    ('medium', 'warm'):  {'olive', 'rust', 'camel', 'gold', 'burnt_orange'},
    ('tan', 'cool'):     {'white', 'navy', 'emerald', 'fuchsia', 'charcoal'},
    ('tan', 'warm'):     {'mustard', 'rust', 'olive', 'cream', 'coral'},
    ('deep', 'cool'):    {'white', 'ice_blue', 'fuchsia', 'emerald', 'royal_blue'},
    ('deep', 'warm'):    {'mustard', 'orange', 'gold', 'cream', 'coral'},
}

# Colors that are known to wash out or clash for a given skin tone depth,
# regardless of undertone — a light hand penalty rather than a hard block.
LOW_CONTRAST_RISK = {
    'fair': {'cream', 'pale_yellow', 'light_grey'},
    'deep': {'brown', 'charcoal', 'navy'} if False else set(),  # deep skin can carry most darks fine
}

def color_score(user_skin_tone, user_undertone, product_color):
    if not product_color:
        return 0.5  # unknown color — neutral score, don't penalize missing data

    key = (user_skin_tone, user_undertone)
    flattering = COLOR_HARMONY.get(key, set())

    if product_color in flattering:
        return 1.0

    if product_color in LOW_CONTRAST_RISK.get(user_skin_tone, set()):
        return 0.2

    return 0.6  # neutral — not a specifically bad match, just not called out as ideal


def body_type_score(user_body_type, product_best_for_body_types):
    if not product_best_for_body_types:
        return 0.5
    allowed = [b.strip() for b in product_best_for_body_types.split(',')]
    if 'all' in allowed or user_body_type in allowed:
        return 1.0
    return 0.4


def occasion_score(user_occasion, product_best_for_occasions):
    if not product_best_for_occasions:
        return 0.5
    allowed = [o.strip() for o in product_best_for_occasions.split(',')]
    if user_occasion in allowed:
        return 1.0
    return 0.3


def height_score(user_height_range, product_silhouette):
    # Structured/fitted pieces tend to elongate shorter frames;
    # relaxed/oversized pieces can overwhelm a shorter frame.
    if not product_silhouette:
        return 0.5
    if user_height_range in ('122-152', '153-182') and product_silhouette == 'relaxed':
        return 0.4
    if user_height_range in ('183-213', '213+') and product_silhouette == 'structured':
        return 0.6
    return 0.7


WEIGHTS = {
    'color': 0.35,
    'body_type': 0.30,
    'occasion': 0.25,
    'height': 0.10,
}


def score_product(profile, product):
    scores = {
        'color': color_score(profile.skin_tone, getattr(profile, 'undertone', None), product.color),
        'body_type': body_type_score(profile.body_type, product.best_for_body_types),
        'occasion': occasion_score(profile.occasion, product.best_for_occasions),
        'height': height_score(profile.height_range, product.silhouette),
    }
    total = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)
    return round(total, 3), scores


def recommend_products(profile, products, top_n=8):
    scored = []
    for product in products:
        total, breakdown = score_product(profile, product)
        scored.append((product, total, breakdown))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n]