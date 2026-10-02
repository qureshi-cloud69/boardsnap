"""
Generate 3 sample board screenshots that match the game's board format:
- vertical rounded-rect tray on wooden background, hex-packed staggered grid 5/6 alternating, ~10 rows
- glossy circular bubble tiles with black uppercase letter + tiny subscript value
- some empty/popped holes
- slight rotation optional
Pillow based renderer.
"""
import os, random, math
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import cv2

SCRABBLE_VALUES = {
    'A': 1, 'B': 3, 'C': 3, 'D': 2, 'E': 1, 'F': 4, 'G': 2,
    'H': 4, 'I': 1, 'J': 8, 'K': 5, 'L': 1, 'M': 3, 'N': 1,
    'O': 1, 'P': 3, 'Q': 10,'R': 1, 'S': 1, 'T': 1, 'U': 1,
    'V': 4, 'W': 4, 'X': 8, 'Y': 4, 'Z': 10
}
# Tinted colors for high-value tiles (visual only)
TINTS = {
    'orange': (255, 165, 0),
    'pink': (255, 105, 180),
    'yellow': (255, 215, 0),
    'green': (50, 205, 50),
    'purple': (147, 112, 219),
}

def get_bold_font(size):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def get_regular_font(size):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def draw_wood_background(w, h):
    # Create wood texture via noise + gradient
    img = Image.new('RGB', (w,h), (120, 70, 30))
    draw = ImageDraw.Draw(img)
    # wood planks: horizontal bands with grain
    plank_h = h // 6
    base_colors = [(139, 69, 19), (160, 82, 45), (205, 133, 63), (139, 69, 19)]
    for i in range(6):
        y0 = i*plank_h
        y1 = y0+plank_h
        col = base_colors[i % len(base_colors)]
        draw.rectangle([0,y0,w,y1], fill=col)
        # grain lines
        for g in range(12):
            y = y0 + g*plank_h//12 + random.randint(-3,3)
            shade = random.randint(-15,15)
            col2 = (max(0,min(255,col[0]+shade)), max(0,min(255,col[1]+shade)), max(0,min(255,col[2]+shade)))
            draw.line([(0,y),(w,y)], fill=col2, width=1)
            # wavy
            if random.random()<0.5:
                draw.line([(w//3,y),(2*w//3,y+random.randint(-2,2))], fill=col2, width=1)
    # add subtle noise
    arr = np.array(img).astype(np.int16)
    noise = np.random.randint(-10,10, arr.shape, dtype=np.int16)
    arr = np.clip(arr + noise*0.3, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)

def create_board_image(board_idx=0, width=480, height=820, seed=None):
    if seed is not None:
        random.seed(seed)
    # Board config: 10 rows alternating 5 and 6
    rows = 10
    # row lengths pattern: even rows 6, odd rows 5? or vice versa. We'll use 6,5,6,5,...
    row_lengths = [6 if r%2==0 else 5 for r in range(rows)]
    total_tiles = sum(row_lengths)  # 55
    # Prepare letters: curated to produce interesting words, plus random
    # For each sample, we embed known high scoring words
    sample_words = [
        ["QUIXOTIC", "JAZZ", "QUICK", "ZEBRA", "OXIDE"],  # sample 0 focuses on high value
        ["STRENGTH", "BLAZING", "PUZZLE", "EXPAND", "GLITCH"], # sample 1
        ["WONDERFUL", "AMAZING", "BRIGHT", "GLOWING", "SHIMMER"], # sample 2
    ]
    # Generate letter distribution that makes board solvable
    # We'll create a base random letter list weighted by English frequency? Then inject words
    # Simpler: generate random letters A-Z, then plant a few words along paths manually? But easier to just random and check solver finds many words.
    # We'll create a list of letters that includes all letters for planting words spread across board.
    inject = sample_words[board_idx % len(sample_words)][0]  # primary word to embed
    # Create hex positions
    # Geometry for 470px wide screenshot: neighbors ±73px horiz, ±55-60 vert.
    # We'll compute positions for our width.
    # Let's set board interior width ~ 360, tray width 400, tile radius ~28, spacing hex
    W, H = width, height
    # Wood background
    bg = draw_wood_background(W,H)

    # Tray: vertical rounded rectangle centered
    tray_w = 380
    tray_h = 680
    tray_x0 = (W - tray_w)//2
    tray_y0 = (H - tray_h)//2 - 10
    tray_x1 = tray_x0 + tray_w
    tray_y1 = tray_y0 + tray_h
    # Draw tray shadow
    draw_bg = ImageDraw.Draw(bg)
    shadow_offset = 8
    # shadow rounded rect
    def rounded_rect(draw, x0,y0,x1,y1, r, fill):
        draw.rounded_rectangle([x0,y0,x1,y1], radius=r, fill=fill)
    # shadow
    rounded_rect(draw_bg, tray_x0+shadow_offset, tray_y0+shadow_offset, tray_x1+shadow_offset, tray_y1+shadow_offset, 28, fill=(60,30,10))
    # tray base (light beige)
    rounded_rect(draw_bg, tray_x0, tray_y0, tray_x1, tray_y1, 28, fill=(240, 230, 210))
    # inner subtle gradient: draw lighter inner rect
    rounded_rect(draw_bg, tray_x0+6, tray_y0+6, tray_x1-6, tray_y1-6, 22, fill=(250, 245, 235))
    # wood tray border (thin)
    draw_bg.rounded_rectangle([tray_x0, tray_y0, tray_x1, tray_y1], radius=28, outline=(180,160,130), width=2)

    # Tile geometry inside tray
    tile_radius = 26
    tile_diameter = tile_radius*2 + 6  # gap
    # hex packing: odd rows offset half tile
    # compute positions
    positions = []  # list of (x,y,row,col)
    start_y = tray_y0 + 45
    row_spacing = 55  # vertical spacing hex ~ 0.866*diameter ~= 45 but spec says 55-60; use 55
    col_spacing = 62  # horizontal spacing ~ tile diameter+gap
    # Center each row horizontally within tray
    for r in range(rows):
        n = row_lengths[r]
        # total width of this row
        row_w = n * col_spacing - 6  # adjust
        # center offset
        offset_x = (tray_w - row_w)//2
        # staggered offset for odd rows: half tile (spec says odd rows offset half tile)
        # But our row_w centering already handles it; however hex staggering is inherent via offset_x shift extra half
        # We'll add extra offset for odd rows
        if r % 2 == 1:
            offset_x += col_spacing//2 - 15
        # y
        y = start_y + r*row_spacing
        for c in range(n):
            x = tray_x0 + offset_x + c*col_spacing + col_spacing//2
            positions.append((x,y,r,c))

    # Now assign letters to positions, with some holes empty
    # Decide holes: 0-4 empties
    hole_counts = [2, 3, 1]
    hole_count = hole_counts[board_idx % len(hole_counts)]
    hole_indices = set(random.sample(range(len(positions)), hole_count))
    # For deterministic demo, fix holes at specific indices
    if board_idx==0:
        hole_indices = {5, 18}  # tweaked
    elif board_idx==1:
        hole_indices = {7, 22, 40}
    elif board_idx==2:
        hole_indices = {12}

    # Letters pool: include some high-value letters
    # We'll construct a board that guarantees many words: use common letters + injected word letters placed adjacently?
    # Instead of random, let's aim to place letters so that a specific high-scoring word is playable via hex path.
    # We could generate random then test via solver? Simpler: For demo, just random but ensure at least one Q, Z, X etc on board 0.
    letters = []
    base_letters = list("EEEEEEEEAAAAAAIIIIIOOOOUUUSSTTRRNNDDLCMPFHGVWYBKJXQZ")
    # Shuffle and pick
    # We'll assign sequentially with random choice biased
    # To make interesting, we predefine letter lists for each board that are known to generate many words
    preset_boards = {
        0: list("S E R A N G T Q U I X O C L D P B M F H W Y K Z U A E I O A S T R N D L".split()),
        1: list("B L A Z I N G P U Z E X Q J K W Q T C H M F D S R N O A E I U Y V R S T E".split()),
        2: list("W O N D E R F U L A M A Z I N G B R I G H T G L O W S H I M E R C D P K U".split()),
    }
    # Clean presets: they are strings with spaces
    preset_map = {}
    # board 0 letters as continuous string? Let's define better
    board_letters_raw = {
        0: "RETAINSQUBLOXCDMPFHGWYKZVAEIOSTRNDLJUQUICKAG",  # 55 approx
        1: "BLAZINGPUZLEQXJKWTCHMFD SRNOAEIUYV RST EANDLGO".replace(" ",""),
        2: "WONDERFULAMAZINGBRIGHTGLOWSHIMERC DPKUVXYZJQT".replace(" ",""),
    }
    raw = board_letters_raw[board_idx]
    # pad/truncate to total_tiles
    # Ensure length matches
    seq = list(raw.replace(" ","").upper())
    # If seq longer than needed truncate, if shorter pad random
    if len(seq) < total_tiles:
        extra = [random.choice("AEIOSRTN") for _ in range(total_tiles - len(seq))]
        seq = seq + extra
    else:
        seq = seq[:total_tiles]
    random.shuffle(seq)  # shuffle so it looks random but same letters
    # However to make word "QUIZ" or "JAZZ" we need specific adjacency. For demo we instead brute force generate board until solver finds high scoring words? Could test.
    # We'll keep shuffled but also guarantee we plant a word sequentially along a path? Approach: pick a path of hex-adjacent tiles and set their letters to spell a target word.

    # Let's define a helper to find a valid hex path of length len(word) in the positions grid,
    target_word = inject  # e.g., QUIXOTIC for board 0 (8 letters)
    # We'll find a path via random walk that visits distinct tiles (no hole) and covers needed length.
    # Use simple DFS to pick path that snakes.
    # Build adjacency for positions (including holes still considered for geometry)
    import math as m
    xs = [p[0] for p in positions]; ys = [p[1] for p in positions]
    # median nearest distance ~ col_spacing ~62, row_spacing 55
    threshold = 70  # approx 1.05*median
    adj = {i:[] for i in range(len(positions))}
    for i in range(len(positions)):
        for j in range(len(positions)):
            if i==j: continue
            if math.hypot(xs[i]-xs[j], ys[i]-ys[j]) < threshold:
                adj[i].append(j)
    # find path for target_word via DFS attempt
    def find_path_for_word(length):
        # try random start
        for attempt in range(200):
            start = random.choice([i for i in range(len(positions)) if i not in hole_indices])
            visited=set([start]); path=[start]
            while len(path)<length:
                cur=path[-1]
                candidates=[n for n in adj[cur] if n not in visited and n not in hole_indices]
                if not candidates:
                    break
                nxt=random.choice(candidates)
                visited.add(nxt); path.append(nxt)
            if len(path)==length:
                return path
        return None
    path_for_word = find_path_for_word(len(target_word))
    # Assign letters along that path to spell target_word
    if path_for_word:
        for idx, tile_idx in enumerate(path_for_word):
            seq[tile_idx] = target_word[idx]

    # Now final letters per position index
    final_letters = seq

    # Slight rotation 1-3 degrees? We'll apply slight rotation to whole image later for realism.
    # Draw bubbles
    draw = ImageDraw.Draw(bg)
    font_big = get_bold_font(26)
    font_small = get_regular_font(10)

    # For each position, draw bubble
    # Bubble style: glossy circular white with subtle shadow and highlight, tint optional
    for idx, (x,y,r,c) in enumerate(positions):
        if idx in hole_indices:
            # empty popped: blank white circle with no letter, slightly darker?
            # Draw empty circle - white with thin gray outline, inner shadow
            # Just draw white circle with gray border
            draw.ellipse([x-tile_radius, y-tile_radius, x+tile_radius, y+tile_radius], fill=(245,245,245), outline=(200,200,200), width=2)
            # inner darker inner circle to show popped hole? Keep simple.
            # Add subtle inner shadow
            draw.ellipse([x-tile_radius+4, y-tile_radius+4, x+tile_radius-4, y+tile_radius-4], fill=None, outline=(230,230,230), width=1)
            continue
        ch = final_letters[idx]
        # Tint? High value tiles tinted randomly 30% chance if value >=3
        val = SCRABBLE_VALUES.get(ch, 1)
        fill_color = (255,255,255)
        if val >= 3 and random.random()<0.4:
            # pick tint
            tint_name = random.choice(list(TINTS.keys()))
            # mix white with tint 30%
            tint = TINTS[tint_name]
            fill_color = tuple(int(0.7*255+0.3*t) for t in tint)
            # alternative soft pastel

        # Draw shadow for bubble
        draw.ellipse([x-tile_radius+1, y-tile_radius+1+2, x+tile_radius+1, y+tile_radius+1+2], fill=(180,170,150))
        # Main bubble white
        draw.ellipse([x-tile_radius, y-tile_radius, x+tile_radius, y+tile_radius], fill=fill_color, outline=(180,180,180), width=1)
        # Gloss highlight: small ellipse top-left
        highlight_w = tile_radius*0.9
        highlight_h = tile_radius*0.6
        hx0 = x - tile_radius*0.5
        hy0 = y - tile_radius*0.6
        hx1 = hx0 + highlight_w
        hy1 = hy0 + highlight_h
        # draw white translucent highlight
        draw.ellipse([hx0, hy0, hx1, hy1], fill=(255,255,255))

        # Letter
        # Center black uppercase
        # Measure letter bbox
        try:
            bbox = draw.textbbox((0,0), ch, font=font_big)
            w1 = bbox[2]-bbox[0]; h1 = bbox[3]-bbox[1]
            tx = x - w1//2 - bbox[0]
            ty = y - h1//2 - bbox[1] - 4  # slightly up to leave space for subscript
            draw.text((tx,ty), ch, fill=(0,0,0), font=font_big)
        except:
            draw.text((x-10,y-12), ch, fill=(0,0,0), font=font_big)

        # Subscript value tiny bottom-right
        val_str = str(val)
        try:
            bbox2 = draw.textbbox((0,0), val_str, font=font_small)
            w2 = bbox2[2]-bbox2[0]; h2 = bbox2[3]-bbox2[1]
            sx = x + tile_radius*0.45 - w2//2
            sy = y + tile_radius*0.35 - h2//2
            draw.text((sx,sy), val_str, fill=(30,30,30), font=font_small)
        except:
            draw.text((x+8,y+6), val_str, fill=(0,0,0), font=font_small)

    # Add slight tilt 1-3 degrees if desired for demo realism? Let's add 1.5° for board 1, -2° for board 2
    tilt_angles = [0, 1.8, -1.5]
    angle = tilt_angles[board_idx % len(tilt_angles)]
    if angle != 0:
        # rotate whole image slightly, fill background with wood extended
        bg = bg.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(139,69,19))
        # Need to keep tray etc rotated; this simulates screenshot tilt.

    # Add subtle vignette / border
    # Resize to expected ~470 width? Our width is 480, so keep.

    return bg, final_letters, positions, hole_indices, path_for_word, target_word

def save_samples(out_dir="backend/samples"):
    os.makedirs(out_dir, exist_ok=True)
    import json
    samples_meta=[]
    for i in range(3):
        img, letters, positions, holes, path, word = create_board_image(board_idx=i, seed=42+i)
        fname = f"sample_{i+1}.png"
        fpath = os.path.join(out_dir, fname)
        img.save(fpath, "PNG")
        print(f"Saved {fpath} target word {word} path {path}")

        # Build meta for frontend: need tile positions? But detection will recompute. Save ground truth for reference.
        meta = {
            "id": i+1,
            "filename": fname,
            "target_word": word,
            "hole_indices": list(holes),
            "positions": [{"x":int(p[0]), "y":int(p[1]), "row":int(p[2]), "col":int(p[3])} for p in positions],
            "letters": letters,
        }
        with open(os.path.join(out_dir, f"sample_{i+1}.json"), "w") as f:
            json.dump(meta, f, indent=2)
        samples_meta.append(meta)
    # also save index
    import json as js
    with open(os.path.join(out_dir, "index.json"), "w") as f:
        js.dump(samples_meta, f, indent=2)

if __name__=="__main__":
    save_samples()
