"""The synthetic replay set for filing (build plan section 7).

The 37 notes of the research doc's mapping table
(docs/research-life-categories.md, section 5), each with its expected life
area, topic and rule. Notes #1-#8 are the owner's real notes, so they are
reworded here; the others are the doc's own made-up examples. Plus the
scenarios from the design discussion. No real personal data.
"""

# (number, note, expected area, expected topic, expected rule)
# A note is a dict like the organizer's: "text", and for sources "source",
# "source_title" and "context" (your own note about why you saved it).
TABLE = [
    (1, {"text": "Have to sit the Python quiz tomorrow at 10:30"}, "learn", "Study", "R5"),
    (2, {"text": "Stop the Netflix subscription before 20 December"}, "money", "Bills & subscriptions", "R2"),
    (3, {"source": "url", "source_title": "Restaurant-style butter chicken | YouTube",
         "text": "A video recipe for butter chicken with cream and tomatoes.",
         "context": "might make this one day"}, "fun", "Cooking", "R3"),
    (4, {"source": "url", "source_title": "Creamy white sauce pasta | YouTube",
         "text": "Step by step white sauce pasta with garlic and cheese.",
         "context": "cook this for my date on Saturday"}, "people", "Occasions & gifts", "R3"),
    (5, {"source": "image", "source_title": "college-halloween-budget.png",
         "text": "Halloween night event budget: decorations 4000, sound 6000, food 9000.",
         "context": "discuss the budget with the admin team of my college"}, "learn", "Study", "R4"),
    (6, {"source": "pdf", "source_title": "Hypothesis testing practice set.pdf",
         "text": "Null and alternative hypotheses, t-tests and p-values, worked problems.",
         "context": "for Statistics"}, "learn", "Study", "R3"),
    (7, {"source": "url", "source_title": "Nemotron coding agent demo | YouTube",
         "text": "An AI coding agent writes and tests code on its own.", "context": ""},
     "learn", "Skills & projects", "R5"),
    (8, {"text": "Pill reminder: which tablets to take morning and night"}, "health", "Medicines & doctors", "R1"),
    (9, {"text": "Electricity bill ₹1,840 due 20 Nov"}, "money", "Bills & subscriptions", "R2"),
    (10, {"text": "Pay rent to landlord by 5th"}, "money", "Bills & subscriptions", "R2"),
    (11, {"text": "Health insurance renews 3 Jan, compare plans"}, "money", "Bank, tax & documents", "R2"),
    (12, {"text": "Buy Crocin and cough syrup"}, "health", "Medicines & doctors", "R1"),
    (13, {"text": "Leg day: squats 4×10, lunges 3×12"}, "health", "Fitness & food", "R5"),
    (14, {"text": "Therapy Thursday 6 pm, talk about exam stress"}, "health", "Mind & mood", "R1"),
    (15, {"text": "Groceries: milk, eggs, atta, onions"}, "money", "Home & errands", "R5"),
    (16, {"text": "Kitchen tap leaking, call plumber"}, "money", "Home & errands", "R5"),
    (17, {"text": "Aarav's parent-teacher meeting at school, Fri 10 am"}, "people", "Family", "R4"),
    (18, {"text": "Mom's thyroid checkup on 12th, book lab test"}, "health", "Medicines & doctors", "R1"),
    (19, {"text": "Ankit's wedding in Jaipur 14 Dec: buy outfit, book train"}, "people", "Occasions & gifts", "R3"),
    (20, {"text": "Priya's birthday 9 Nov, order a gift"}, "people", "Occasions & gifts", "R3"),
    (21, {"text": "Goa trip with college friends 26–29 Dec: book hostel"}, "fun", "Trips & places", "R5"),
    (22, {"text": "Thailand visa appointment 8 Jan"}, "fun", "Trips & places", "R3"),
    (23, {"text": "Passport expires Mar 2027, renew"}, "money", "Bank, tax & documents", "R2"),
    (24, {"text": "Flight DEL→GOI 26 Dec 06:10, PNR X7K2Q"}, "fun", "Trips & places", "R3"),
    (25, {"text": "Read Atomic Habits"}, "fun", "Watch, read & listen", "R5"),
    (26, {"text": "Podcast: Freakonomics episode on tipping"}, "fun", "Watch, read & listen", "R5"),
    (27, {"text": "Watch Panchayat S4 on Prime"}, "fun", "Watch, read & listen", "R5"),
    (28, {"text": "'We suffer more in imagination than in reality' (Seneca)"}, "fun", "Watch, read & listen", "R5"),
    (29, {"text": "App idea: split-bill app that reads UPI SMS"}, "learn", "Skills & projects", "R5"),
    (30, {"text": "Startup idea: tiffin subscription for hostel students"}, "learn", "Skills & projects", "R5"),
    (31, {"text": "Home wifi password (router sticker)"}, "money", "Home & errands", "R5"),
    (32, {"text": "Google interview round 2 Tue, revise DSA"}, "learn", "Work & career", "R3"),
    (33, {"text": "Salary credited, move ₹5,000 to RD"}, "money", "Bank, tax & documents", "R2"),
    (34, {"text": "File ITR before 31 July"}, "money", "Bank, tax & documents", "R2"),
    (35, {"text": "Car service due at 10,000 km, book slot"}, "money", "Home & errands", "R5"),
    (36, {"text": "Bruno's rabies shot at the vet, 18 Nov"}, "money", "Home & errands", "R5"),
    (37, {"text": "Felt low after mid-sem result, need to talk to someone"}, "health", "Mind & mood", "R1"),
]

# The scenarios from the design discussion: (note, expected area or None for
# "asks in Needs you", expected topic or None).
SCENARIOS = [
    ({"text": "Quiz moved to Thursday"}, "learn", "Study"),
    ({"text": "Buy cream and pasta"}, "money", "Home & errands"),
    ({"text": "Talk to admin about the budget again"}, "learn", "Study"),
    ({"text": "Call Aditi"}, None, None),
    ({"source": "url", "source_title": "Building agents with LangGraph | YouTube",
      "text": "A tutorial on building AI agents.", "context": ""}, "learn", "Skills & projects"),
    ({"text": "Buy a gift for Riya's birthday"}, "people", "Occasions & gifts"),
    ({"text": "Kal quiz hai"}, "learn", "Study"),
    ({"text": "Doc appt Monday"}, None, None),
]


def notes():
    """The table as organizer notes, numbered 1-37."""
    return [{"id": number, **note} for number, note, *_ in TABLE]
