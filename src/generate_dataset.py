"""Generate a synthetic dataset of Bangladeshi name variants for duplicate detection.

Each base person gets an "original" record plus 3-8 noisy variants. Then 20% extra
"hard_negative" persons are added: different people whose names are close to an
existing person's (Rahim vs Karim).

Usage:
    python src/generate_dataset.py                  # 400 base names -> data/names.csv
    python src/generate_dataset.py --size 5000 --seed 7 --out data/names_5k.csv
"""
import argparse
import csv
import random
import re
import string
from pathlib import Path

# ---------------------------------------------------------------- name pools
MUSLIM_MALE = [
    "Abdur", "Abdul", "Rahim", "Karim", "Kamal", "Jamal", "Hasan", "Habib", "Rafiq",
    "Shafiq", "Nasir", "Sohel", "Faruk", "Rubel", "Monir", "Zakir", "Nazmul", "Rezaul",
    "Mizanur", "Habibur", "Ashraf", "Mostafa", "Shahid", "Shakil", "Tanvir", "Imran",
    "Arif", "Jahid", "Saiful", "Anisur", "Mahbub", "Farhad", "Zahid", "Shoaib", "Rakib",
    "Sabbir", "Mamun", "Ziaur", "Ashik", "Rashed",
]
MUSLIM_FEMALE = [
    "Fatema", "Nusrat", "Tahmina", "Shirin", "Nasreen", "Sharmin", "Ayesha", "Rokeya",
    "Jannatul", "Farzana", "Sadia", "Taslima", "Rehana", "Shahnaz", "Nazma", "Rumana",
    "Salma", "Rabeya", "Tania", "Shathi", "Mahmuda", "Lubna", "Ishrat", "Zannat",
]
MUSLIM_MIDDLE_M = ["Ahmed", "Ali", "Hossain", "Uddin", "Ullah", "Kabir", "Nur"]
MUSLIM_MIDDLE_F = ["Ara", "Jahan", "Nur", "Sultana", "Akter"]
MUSLIM_SURNAME_M = [
    "Rahman", "Islam", "Hossain", "Ahmed", "Uddin", "Alam", "Khan", "Chowdhury", "Miah",
    "Sarker", "Talukder", "Mollah", "Sheikh", "Siddique", "Haque", "Kabir", "Bhuiyan",
    "Mahmud", "Zaman", "Faruque", "Ali",
]
MUSLIM_SURNAME_F = [
    "Akter", "Begum", "Khatun", "Sultana", "Parvin", "Nahar", "Ferdousi", "Islam",
    "Rahman", "Chowdhury", "Haque",
]
HINDU_MALE = [
    "Amit", "Sujit", "Dilip", "Pradip", "Sudip", "Partha", "Ripon", "Ratan", "Shuvo",
    "Subrata", "Debashish", "Tapash", "Ashok", "Gopal", "Biplob", "Sanjoy", "Joydeb",
    "Prosenjit", "Shyamal", "Nirmal", "Uttam", "Bijoy", "Rajesh", "Sourav", "Shankar",
    "Anup", "Pankaj", "Deepak", "Kishore", "Pritam",
]
HINDU_FEMALE = [
    "Rina", "Mitu", "Shipra", "Puja", "Ruma", "Shampa", "Mousumi", "Sumi", "Joya",
    "Lipika", "Anjali", "Priya", "Deepa", "Sreelekha", "Shreya",
]
HINDU_MIDDLE_M = ["Kumar", "Chandra", "Kanti", "Ranjan", "Lal"]
HINDU_MIDDLE_F = ["Rani", "Bala", "Lata"]
HINDU_SURNAME = [
    "Das", "Dey", "Roy", "Saha", "Sen", "Ghosh", "Bose", "Chakraborty", "Banerjee",
    "Mukherjee", "Biswas", "Sarkar", "Paul", "Mondal", "Dutta", "Bhattacharjee",
    "Majumder", "Haldar", "Shil", "Karmakar", "Debnath",
]
ENGLISH_GIVEN = [
    "Joseph", "Philip", "Stephen", "Christopher", "Peter", "Jerome", "Anthony", "Francis",
    "Paul", "Ronald", "Raphael", "Michael", "John", "David", "Robin", "Sunny", "Tony",
    "Jenny", "Mary", "Agnes", "Rita", "Monica", "Sophia", "Linda", "Ruth", "Nancy",
    "Sharon", "Esther",
]
ENGLISH_SURNAME = [
    "Gomes", "D'Costa", "Rozario", "Gonsalves", "Corraya", "Pereira", "Baroi",
    "Rodrigues", "Cruze", "Palma",
]

MALE_PREFIXES = ["Md.", "Md", "Mohd.", "Mohammad", "Muhammad", "Mohammed"]
FEMALE_PREFIXES = ["Mst.", "Most.", "Mosammat", "Musammat"]
PREFIX_KEYS = {p.lower().rstrip(".") for p in MALE_PREFIXES + FEMALE_PREFIXES}

# Different real names that look/sound close. Alternatives are chosen so they are
# NOT spelling variants of the original (e.g. no Sabbir -> Sabir).
CONFUSABLE = {
    # Muslim given names
    "Rahim": ["Karim", "Rakib"], "Karim": ["Rahim", "Kabir"], "Kamal": ["Jamal", "Kamrul"],
    "Jamal": ["Kamal", "Jalal"], "Hasan": ["Hasib", "Hasin"], "Habib": ["Hasib", "Hamid"],
    "Rafiq": ["Rakib", "Tarik"], "Shafiq": ["Shafi", "Sadiq"], "Nasir": ["Nasim", "Basir"],
    "Sohel": ["Sohag", "Soheb"], "Faruk": ["Farid", "Fahim"], "Rubel": ["Ruhul", "Rubayet"],
    "Monir": ["Mahir", "Mohin"], "Zakir": ["Zahir", "Zakaria"], "Zahid": ["Zahir", "Zayed"],
    "Imran": ["Imon", "Irfan"], "Arif": ["Asif", "Arafat"], "Shakil": ["Shakib", "Shamil"],
    "Tanvir": ["Tamim", "Tanim"], "Rakib": ["Rakin", "Rafiq"], "Sabbir": ["Sakib", "Sajid"],
    "Mamun": ["Masum", "Mahmud"], "Rashed": ["Rasel", "Rayhan"], "Ashik": ["Atik", "Asif"],
    "Fatema": ["Fahima", "Fatin"], "Nusrat": ["Nasrin", "Nurjahan"],
    "Tahmina": ["Tahsina", "Tamanna"], "Sharmin": ["Shamima", "Sharmila"],
    "Ayesha": ["Anisha", "Alisha"], "Salma": ["Sabina", "Selima"], "Rehana": ["Reshma", "Rubana"],
    "Tania": ["Tasnia", "Tanha"], "Sadia": ["Sabiha", "Nadia"], "Nazma": ["Nazia", "Nasima"],
    # Hindu given names
    "Amit": ["Ajit", "Sumit"], "Sujit": ["Sujoy", "Surjit"], "Dilip": ["Dipak", "Dilwar"],
    "Ratan": ["Rajan", "Ripon"], "Ripon": ["Ratan", "Rupon"], "Ashok": ["Alok", "Asim"],
    "Gopal": ["Gobinda", "Gopi"], "Sanjoy": ["Sanjib", "Sanjit"], "Sourav": ["Gourav", "Pranab"],
    "Shankar": ["Shekhar", "Shibu"], "Anup": ["Anik", "Arup"], "Deepak": ["Dipankar", "Deepto"],
    "Puja": ["Pinki", "Pritha"], "Rina": ["Rita", "Mina"], "Priya": ["Piya", "Pritha"],
    "Deepa": ["Dipti", "Rupa"], "Sumi": ["Sumita", "Rumi"], "Ruma": ["Rumi", "Ruhi"],
    "Shampa": ["Champa", "Shapla"],
    # English-style given names
    "Peter": ["Patrick", "Pius"], "Paul": ["Saul", "Raul"], "John": ["Joel", "Jonas"],
    "Michael": ["Mitchell", "Micah"], "Stephen": ["Simon", "Stanley"], "Mary": ["Molly", "Mona"],
    "Rita": ["Rina", "Ritu"], "Linda": ["Lina", "Lisa"], "Tony": ["Tommy", "Toby"],
    "David": ["Daniel", "Dennis"], "Robin": ["Rodney", "Roman"],
    # Surnames
    "Rahman": ["Rahim", "Raihan"], "Islam": ["Alam", "Aslam"], "Alam": ["Islam", "Aslam"],
    "Hossain": ["Hasan", "Haider"], "Ahmed": ["Ahsan", "Hamid"], "Uddin": ["Ullah", "Uzzaman"],
    "Das": ["Dey", "Dam"], "Dey": ["Das", "Deb"], "Sen": ["Sil", "Son"], "Ghosh": ["Bose", "Gope"],
}

# ------------------------------------------------------------------- helpers
def name_key(name):
    """Identity key: lowercase letters only, honorific prefixes dropped.

    Two different persons must never share a key, so ground-truth labels stay clean.
    """
    tokens = [t for t in name.lower().split() if t.rstrip(".") not in PREFIX_KEYS]
    return re.sub(r"[^a-z]", "", "".join(tokens))


def make_base(rng):
    kind = rng.choices(
        ["muslim_m", "muslim_f", "hindu_m", "hindu_f", "english"], weights=[40, 15, 18, 12, 15]
    )[0]
    if kind == "muslim_m":
        prefix = rng.choices(["", "Md.", "Mohammad", "Sheikh Mohammad", "Syed"],
                             weights=[40, 30, 15, 10, 5])[0]
        given, middle, surnames = MUSLIM_MALE, MUSLIM_MIDDLE_M, MUSLIM_SURNAME_M
    elif kind == "muslim_f":
        prefix = rng.choices(["", "Mst.", "Mosammat"], weights=[60, 25, 15])[0]
        given, middle, surnames = MUSLIM_FEMALE, MUSLIM_MIDDLE_F, MUSLIM_SURNAME_F
    elif kind == "hindu_m":
        prefix, given, middle, surnames = "", HINDU_MALE, HINDU_MIDDLE_M, HINDU_SURNAME
    elif kind == "hindu_f":
        prefix, given, middle, surnames = "", HINDU_FEMALE, HINDU_MIDDLE_F, HINDU_SURNAME
    else:
        prefix, given, middle, surnames = "", ENGLISH_GIVEN, ENGLISH_GIVEN, ENGLISH_SURNAME

    parts = [prefix, rng.choice(given)]
    if rng.random() < 0.3:
        parts.append(rng.choice(middle))
    parts.append(rng.choice(surnames))
    tokens = " ".join(p for p in parts if p).split()
    if len(set(tokens)) < len(tokens):  # e.g. "Paul Paul Gomes"
        return kind, None
    return kind, " ".join(tokens)


# --------------------------------------------------------------- variant rules
def _swap(name, pairs, rng):
    """Replace one random regex match from `pairs` [(pattern, replacement), ...]."""
    options = [(m.start(), m.end(), new)
               for pat, new in pairs for m in re.finditer(pat, name, re.I)]
    if not options:
        return name
    s, e, new = rng.choice(options)
    if name[s].isupper():
        new = new.capitalize()
    return name[:s] + new + name[e:]


def _prefix(name, kind, rng):
    choices = {"muslim_m": MALE_PREFIXES, "muslim_f": FEMALE_PREFIXES}.get(kind)
    if not choices:
        return name
    tokens = name.split()
    for i, t in enumerate(tokens):
        if t.lower().rstrip(".") in PREFIX_KEYS:
            if rng.random() < 0.25:  # drop the prefix entirely
                return " ".join(tokens[:i] + tokens[i + 1:])
            tokens[i] = rng.choice([p for p in choices if p != t])
            return " ".join(tokens)
    return rng.choice(choices) + " " + name


def _double(name, kind, rng):
    idx = [i for i, c in enumerate(name)
           if i > 0 and c.isalpha() and name[i - 1].isalpha() and c.lower() in "aeioulmnrst"
           and name[i - 1].lower() != c.lower()
           and (i + 1 == len(name) or name[i + 1].lower() != c.lower())]
    if not idx:
        return name
    i = rng.choice(idx)
    return name[:i + 1] + name[i].lower() + name[i + 1:]


def _initials(name, kind, rng):
    tokens = name.split()
    if len(tokens) < 2:
        return name
    inits = [t[0].upper() + "." for t in tokens[:-1]]
    return rng.choice([" ", ""]).join(inits) + " " + tokens[-1]


def _word_order(name, kind, rng):
    tokens = name.split()
    if len(tokens) < 2:
        return name
    return tokens[-1] + rng.choice([" ", ", "]) + " ".join(tokens[:-1])


def _typo(name, kind, rng):
    idx = [i for i, c in enumerate(name) if c.isalpha()]
    i = rng.choice(idx)
    letter = rng.choice(string.ascii_lowercase)
    op = rng.choice(["sub", "del", "ins", "swap"])
    if op == "sub":
        return name[:i] + (letter.upper() if name[i].isupper() else letter) + name[i + 1:]
    if op == "del":
        return name[:i] + name[i + 1:]
    if op == "ins":
        return name[:i + 1] + letter + name[i + 1:]
    # swap two adjacent letters inside a word (not the capital at word start)
    if 0 < i < len(name) - 1 and name[i - 1].isalpha() and name[i + 1].isalpha():
        return name[:i] + name[i + 1] + name[i] + name[i + 2:]
    return name


def _spacing(name, kind, rng):
    tokens = name.split()
    opts = [name + " ", " " + name]
    if len(tokens) > 1:
        i = rng.randrange(1, len(tokens))
        left, right = " ".join(tokens[:i]), " ".join(tokens[i:])
        opts.append(left + "   "[: rng.randint(2, 3)] + right)  # "Md.  Rahim"
        opts.append(left.rstrip(".") + "." + right)             # "Md.Rahim"
    opts.append(name.replace(".", "") if "." in name else name.replace(" ", ". ", 1))
    return rng.choice(opts)


def _case(name, kind, rng):
    return rng.choice([name.upper(), name.lower(), name.swapcase()])


RULES = {
    "prefix": _prefix,
    "vowel": lambda n, k, r: _swap(n, [("a", "o"), ("o", "a"), ("o", "u"), ("u", "o"),
                                       ("i", "e"), ("e", "i")], r),
    "double_letter": _double,
    "sh_s": lambda n, k, r: _swap(n, [("sh", "s"), ("s(?!h)", "sh")], r),
    "ph_f": lambda n, k, r: _swap(n, [("ph", "f"), ("f", "ph")], r),
    "z_j": lambda n, k, r: _swap(n, [("z", "j"), ("j", "z")], r),
    "oo_u": lambda n, k, r: _swap(n, [("oo", "u"), (r"(?<=[a-z])u(?![aeiou])", "oo")], r),
    "ee_i": lambda n, k, r: _swap(n, [("ee", "i"), (r"(?<=[a-z])i(?![aeiou])", "ee")], r),
    "initials": _initials,
    "word_order": _word_order,
    "typo": _typo,
    "spacing": _spacing,
    "case": _case,
}
RULE_NAMES = list(RULES)


def make_variants(name, kind, rng, k, owner, pid):
    """Return up to k distinct (variant, rule) pairs; `owner` maps key -> person_id."""
    variants, seen = [], {name}
    for _ in range(200):
        if len(variants) == k:
            break
        vtype = rng.choice(RULE_NAMES)
        v = RULES[vtype](name, kind, rng)
        key = name_key(v)
        if v in seen or not key or owner.get(key, pid) != pid:
            continue  # unchanged, duplicate, or would collide with another person
        seen.add(v)
        owner[key] = pid
        variants.append((v, vtype))
    return variants


def make_hard_negative(name, rng, owner):
    tokens = name.split()
    opts = [(i, alt) for i, t in enumerate(tokens) for alt in CONFUSABLE.get(t, [])]
    rng.shuffle(opts)
    for i, alt in opts:
        candidate = " ".join(tokens[:i] + [alt] + tokens[i + 1:])
        if name_key(candidate) not in owner:
            return candidate
    return None


# ---------------------------------------------------------------------- main
def generate(size=400, seed=42, neg_ratio=0.2):
    rng = random.Random(seed)
    owner, bases = {}, []
    for _ in range(size * 100):
        if len(bases) == size:
            break
        kind, name = make_base(rng)
        if name and name_key(name) not in owner:
            bases.append((kind, name))
            owner[name_key(name)] = len(bases)
    if len(bases) < size:
        raise ValueError(f"could only build {len(bases)} unique base names (asked {size})")

    rows = []
    for pid, (kind, name) in enumerate(bases, 1):
        rows.append((pid, name, "original"))
        k = rng.randint(3, 8)
        rows += [(pid, v, t) for v, t in make_variants(name, kind, rng, k, owner, pid)]

    n_neg, pid = round(size * neg_ratio), size
    for _, name in rng.sample(bases, len(bases)):
        if pid - size == n_neg:
            break
        neg = make_hard_negative(name, rng, owner)
        if neg:
            pid += 1
            owner[name_key(neg)] = pid
            rows.append((pid, neg, "hard_negative"))

    rng.shuffle(rows)  # so record_id order doesn't leak person grouping
    return [{"record_id": i, "person_id": p, "full_name": n, "variant_type": t}
            for i, (p, n, t) in enumerate(rows, 1)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--size", type=int, default=400, help="number of base persons (default 400)")
    ap.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parents[1] / "data" / "names.csv")
    args = ap.parse_args()

    rows = generate(args.size, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["record_id", "person_id", "full_name", "variant_type"])
        w.writeheader()
        w.writerows(rows)
    n_neg = sum(r["variant_type"] == "hard_negative" for r in rows)
    print(f"wrote {len(rows)} records ({args.size} persons + {n_neg} hard negatives) -> {args.out}")


if __name__ == "__main__":
    main()
