# Research: Core life categories for Life Inbox

Accessed: 2026-11-02 (all sources below were read on this date)

> **Method note.** Pages were fetched with curl and read as text, or read in a
> browser where a site blocks scripts (OECD, BLS, MIT Press). The ACM Digital
> Library blocked full-text access with a bot check, so for four ACM papers
> only the authors' abstract was read (via OpenAlex metadata). These are marked
> *(abstract only)*. Secondary sources are marked *(secondary)*. Sections 3 to 6
> are **analysis and recommendation, not sourced fact**. They are built on the
> evidence in sections 1 and 2.

## Summary

- **Recommend five core categories, with no catch-all.** Travel becomes a subcategory.

  | # | Category (bot name) | Default subcategories (max 3) |
  |---|---|---|
  | 1 | **Learning & work** | Study · Work & career · Skills & projects |
  | 2 | **Money & home** | Bills & subscriptions · Bank, tax & documents · Home & errands |
  | 3 | **Health** | Medicines & doctors · Fitness & food · Mind & mood |
  | 4 | **People** | Family · Friends & partner · Occasions & gifts |
  | 5 | **Fun & interests** | Watch, read & listen · Cooking & hobbies · Trips & places |

- **Why five.** WHO, OECD, the Personal Wellbeing Index, the Wheel of Life, PARA and the time-use surveys keep returning to five areas: health, money and household, work and learning, relationships, and leisure [2][3][5][7][8][11]. GTD says people have "four to seven major areas of responsibility" [9].
- **Drop "Personal / Reference".** "Reference" is a *reason for keeping* a note, not a part of life. It applied to 47% of coded notes in a two-year note-taking study [17]. "Personal" describes everything in the app. Unclear notes should wait in **Needs you** instead of going into a dumping-ground category.
- **Travel is not a top-level area in any framework reviewed.** ATUS and the UN time-use standard (ICATUS) count travel under whatever activity the trip serves [12][13]. Cortana users filed "book hotel, flight" and "renew passport" as *chores* [14].
- **Category is not the same as time or type.** Reminders, dates and formats (video, PDF, link) are separate axes. Desks serve "finding" and "reminding" separately [20]. Reminder task types are verbs that cut across every life area [14]. Notes "did not naturally fall into established PIM data types" [16].
- **Tie-break order for ambiguous notes:** health data → bills and paperwork → the purpose the user states → whose responsibility it is → the topic → ask the user (§4).

---

## 1. Framework comparison

| Framework | Top-level domains (as named by the source) | What it suggests for an inbox app |
|---|---|---|
| **WHOQOL-100** (WHO) | 6 domains: Physical capacity; Psychological; Level of independence; Social relationships; Environment; Spirituality/religion/personal beliefs. Environment facets: safety, home environment, financial resources, access to care, opportunities for new information and skills, recreation/leisure, physical environment, transport [2] (Table 1.4). WHO defines quality of life as perception of one's position in life "in relation to their goals, expectations, standards and concerns" [1]. | Body, mind and medication dependence sit in neighbouring domains, so **one Health area** fits. Home, money and transport share one domain (Environment), which supports **Money & home**. Leisure and learning are facets, not domains. |
| **WHOQOL-BREF** (WHO) | 4 domains: Physical health; Psychological; Social relationships; Environment. Spirituality was folded in "to avoid a single item domain"; the WHOQOL-100 data also hinted that four domains may fit better [2] (Ch. 5). | WHO itself cut 6 domains to 4 for a short instrument. A few broad areas are enough. |
| **OECD Well-being Framework / Better Life Index** | 11 current well-being dimensions in 3 groups [3][4]. *Material conditions:* income and wealth, housing, work and job quality. *Quality of life:* health, knowledge and skills, environmental quality, subjective well-being, safety. *Community relationships:* work-life balance, social connections, civic engagement. The BLI "has been updated in 2025" to match the framework [3]. | Money and housing are grouped as **material conditions**. Leisure time is grouped with social life. Environment and safety rarely appear in personal notes. |
| **Personal Wellbeing Index** (Cummins / International Wellbeing Group, Deakin) | 7 domains: standard of living, health, achieving in life, relationships, safety, community-connectedness, future security. These "represent the first level of deconstruction" of "How satisfied are you with your life as a whole?" [5]. Spiritual/religious item is optional *(secondary)* [6]. | This is the smallest set that claims to cover life as a whole. It maps cleanly onto our five categories, but **PWI has no leisure domain**. Leisure comes from WHOQOL, OECD, the Wheel of Life and ATUS. |
| **Wheel of Life** (Success Motivation International) | 6 areas: Family and home; Financial and career; Mental and education; Physical and health; Social and cultural; Spiritual and ethical. Users rate "the six most important areas of your life" from 1 to 10 [7]. Attribution to Paul J. Meyer in the 1960s: *secondary only, not verified*. | Precedent for **two-word paired area names**. Note that it pairs home with family and career with money; we pair them differently (§3.6). |
| **PARA** (Tiago Forte) | Projects, Areas, Resources, Archives: "only four categories that encompass all the information in your life". Personal Areas include "Health, Finances, Kids, Writing, Car, or Home". Resources are topics of interest such as "Coffee", "Photography" and "Japanese language" [8]. | Organise "according to the projects and goals you are committed to", not broad subjects ("organize by actionability") [8]. This supports **"stated purpose wins"**. Archives is a *state*, not a category. Resources roughly equals **Fun & interests**. A trip ("plan a family vacation") is an outcome or project, not an area [8]. |
| **GTD Horizons of Focus** (David Allen) | Horizon 2, "Areas of focus and accountability": "the four to seven major areas of responsibility" [9]; "Important spheres of work and life to be maintained at standards" [10]. | Practitioner norm is **4 to 7 top-level areas**. Five is in the middle. |
| **American Time Use Survey 2025** (BLS) | Major categories: personal care; eating and drinking; household activities; purchasing goods and services; caring for household members; caring for nonhousehold members; work; education; organizational, civic and religious; leisure and sports; phone calls, mail and email; other [11]. | Shows where waking life actually goes (numbers in §2.4). "All major activity categories include related travel time" [11]. |
| **ICATUS 2016** (UN Statistics Division) | 9 major divisions: employment; production for own use; unpaid domestic services; unpaid caregiving; unpaid volunteer/trainee work; learning; socializing, community and religious practice; culture, leisure, mass media and sports; self-care and maintenance. Each has its own "travelling related to …" division [13]. Employment includes "training and studies in relation to employment" [13]. | The international standard has **no stand-alone travel domain**, and it puts job-related study inside employment. This supports a combined **Learning & work**. |

Maslow's hierarchy was not used. It ranks needs by priority; it does not divide everyday activities into areas. *(Analysis.)*

---

## 2. Evidence: what people actually save and remind themselves of

### 2.1 Reminders: Cortana logs (Graus, Bennett, White, Horvitz, UMAP 2016) [14]

- **Data:** 576,080 confirmed time-based reminders from 92,264 US users (Jan to Feb 2015) were used for the analysis. About 1.5M reminders (Jan to Jun 2015) were used for prediction.
- **Taxonomy:** six task types. The percentages are shares of the 2,484 frequent verb+object task descriptions, which cover 21.7% of the sample.

| Task type | Share | Sub-types / examples from the paper |
|---|---|---|
| Go somewhere | 33.0% | Run errand 83.2% ("pick up milk", "prescription", "dry cleaning"); switch context 16.8% ("go to work") |
| Chores | 23.8% | Recurring 66.5% ("take out trash", "pay rent, bills, phone bill", "feed dogs"); standalone 33.5% ("cancel amazon prime, netflix", "renew … driver's license, passport", "book hotel, flight", "submit timesheet") |
| Communicate | 21.1% | General 94.7% ("call mom"); coordinate 5.3% ("make doctor's appointment") |
| Manage ongoing external process | 12.9% | "turn off stove", "laundry", "pizza in oven" |
| Manage ongoing user activity | 6.3% | Prepare 31.4%, start 61.4%, stop 7.2% ("start studying", "watch the walking dead", "finish homework") |
| Eat / consume | 2.8% | "have lunch", "take medicine" |

- About 80% of reminders fire within 24 hours, and about 25% within the same hour.
- **Limits stated by the authors:** one locale (US), time-based reminders only, and labels assigned manually by the researchers.
- **Takeaway:** these are *action types* that cut across life areas. They should drive task and reminder extraction, not categories. In one "Chores" class, users mixed household jobs (trash, laundry) with money and paperwork (rent, bills, cancelling Netflix, renewing a passport). *(Analysis.)*

### 2.2 Notes-to-self

| Study | Sample | Key numbers |
|---|---|---|
| **Information scraps** (Bernstein, Van Kleek, Karger, schraefel, ACM TOIS 2008) [15] | 27 knowledge workers, 5 organisations, 533 scraps | Most common types: to-dos 92, meeting notes 44, name/contact 38, how-tos 25. **Long tail:** types seen only once make up about one eighth (12.8%) of all scraps, and types seen at most twice make up 18.4%. Half of all scraps belong to types seen 9 times or fewer. The tail includes recipe, gym to join, insurance claim, tax information, planned trip (map), concert tickets, salary calculation, favourite quote and guitar chords. Roles: temporary storage, cognitive support, archiving, reminding. |
| **Note to Self** (Van Kleek et al., CHI 2009) [16] | 42 participants, 10 days | Median note is 7 words. 50% were captured in 10 s or less, and 75% were never edited. Notes "combined information of multiple types", and "people's notes did not naturally fall into established PIM data types". Users appended purpose words as metadata (e.g. "… to do classes"). |
| **Finders/keepers** (Van Kleek, Styke, schraefel, Karger, CHI 2011) [17] | 420 users, 66,151 notes, Aug 2008 to Aug 2010 | Roles of coded notes (n=473; a note could have several): **memory trigger 66%, reference 47%, personal archive 13%, external cognition 12%, journal 9%**. Calendar events, contacts, to-dos and bookmarks made up 51% of a 540-note sample. The rest included passwords, tracking codes, itineraries, recipes and code. In a survey, the most-kept items were "things to look up some day, ideas/brainstorming, short and long-term to-dos and things pasted from the web". Users' own tags included "@work", "@home" and "home - photo". |
| **Mobile memos** (Dai, Lutters, Bower, CHI EA 2005) [18] *(abstract only)* | Interviews with expert PDA users | "Structured tools were routinely avoided for informal note taking in favor of unstructured ones." |
| **Micronote lifecycle** (Lin, Lutters, Kim, CHI 2004) [19] *(abstract only)* | Field study | Micronotes serve "immediate use, temporary storage, and prospective memory aid". |

**Takeaway:** a note's *format or type* (link, PDF, to-do) and its *role* (reminder, reference) cut across all of life. Neither works as a top-level category. Life areas do, with reminders and reference handled as features and states. *(Analysis.)*

No peer-reviewed content analysis of today's phone notes apps (Apple Notes, Google Keep) was found. Neither Apple nor Google publishes usage categories for its list or notes apps.

### 2.3 How people organise personal information

- **Malone (1983)** [20] *(abstract only)*: desks serve two functions, to "remind the user of things to do, not just to help the user find" things. "The cognitive difficulty of categorizing information" shapes how people organise. Malone recommends "doing as much automatic classification as possible".
- **Barreau & Nardi (1995)** [21]: users "preferred location-based finding because of its crucial reminding function" and "avoided elaborate filing schemes". They worked with ephemeral, working and archived information.
- **Bergman et al. (2008)** [22] *(abstract only)*: users estimated they used navigation for "56-68% of file retrieval events but searched for only 4-15%", even with improved desktop search. Search was "a last resort".
- **Bergman & Whittaker (2016)** [23]: folders remain preferred. They describe personal collections as "curation" and propose a "user-subjective approach".
- **Jones, *Keeping Found Things Found*** [24]: PIM covers keeping, re-finding ("Where did I put it?"), and organising and maintaining. One of the first keeping questions he lists is "At home or at work?"
- **Bellotti et al. (2004)** [25] *(abstract only)*: "people are not poor at prioritizing". They spread to-dos across an average of 11.25 tools (reported by [15]).
- **Blandford & Green (2001)** [26]: of 16 university staff, some keep one diary for all of life and some keep separate home and work diaries. The authors write that British academic life "permits no definite separation between home life and work".

**Takeaway:** keep a **small, stable, browsable top level**. Let the AI classify, let user corrections win, and **write tie-break rules down**, because the work/home boundary leaks. *(Analysis.)*

### 2.4 Where time goes: ATUS 2025 (population age 15+, per day) [11]

| Major category | Avg hours | % doing it on an average day |
|---|---|---|
| Personal care (incl. sleep 9.03 h) | 9.80 | 99.9% |
| **Leisure and sports** (TV 2.61 h; socializing 0.58 h; sports/exercise 0.34 h) | **5.16** | **95.1%** |
| Working and work-related | 3.32 | 41.5% |
| **Household activities** | **1.99** | **80.9%** |
| Eating and drinking | 1.21 | 96.9% |
| Purchasing goods and services | 0.69 | 39.7% |
| Caring for household members | 0.49 | 22.0% |
| Educational activities | 0.44 | 8.5% (5.17 h for those who did) |
| Organizational, civic, religious | 0.28 | 13.6% |
| Phone calls, mail, email | 0.19 | 19.2% |
| Caring for nonhousehold members | 0.15 | 7.6% |

ATUS coding rules that matter for boundaries [12]:

- Household activities include housework, cooking, pet care, "vehicle maintenance and repair", home repair, and household management "such as filling out paperwork or planning a party".
- Purchasing includes "financial services and banking", medical, veterinary and government services (licences, fees).
- Food preparation "is always classified as a household activity", even "making breakfast for my son".
- Childcare includes "assisting with homework" and "attending children's events".
- Travel is counted under the activity it serves, e.g. "driving to the stadium" counts as Leisure.

**Takeaway:** leisure is the biggest block of waking time, and household plus purchasing activities touch about 81% of people every day. Both need a home. Education is rare across the population but intense for the people who do it (students). *(Analysis.)*

---

## 3. Recommendation: five core categories *(analysis)*

### 3.1 Learning & work

**Definition:** what you study, earn a living from, or build skills for.

| | |
|---|---|
| Belongs | Classes, quizzes, exams, assignments, study material; college admin, clubs and events you help run; jobs, internships, interviews, meetings, CV; self-learning, tech tutorials, side projects, app or startup ideas; business trips |
| Not here | Paying course fees (Money & home). Leisure reading (Fun & interests). Your child's school (People). |
| **Study** | Courses, exams, assignments, study notes, and college life you take part in (admin, clubs, events). |
| **Work & career** | Job or internship tasks, meetings, interviews, applications, salary talks, colleagues, work travel. |
| **Skills & projects** | Self-directed learning, tutorials, tools to try, side projects, app and startup ideas. |

### 3.2 Money & home

**Definition:** running your household and your own money.

| | |
|---|---|
| Belongs | Rent, utilities, EMIs, subscriptions and memberships (pay, renew, cancel), fees; bank, salary received, savings, tax, insurance; IDs (passport, licence, PAN/Aadhaar), warranties; groceries, shopping, chores, repairs, appliances, car, pets, household info (wifi, addresses, service contacts) |
| Not here | A college or employer's budget (Learning & work). A gift for someone (People). Bookings for a specific trip (Fun & interests). |
| **Bills & subscriptions** | Anything you pay or cancel on a schedule: rent, bills, EMIs, subscriptions, memberships, fees. |
| **Bank, tax & documents** | Accounts, savings, salary received, investments, tax filing, insurance policies, IDs, warranties. |
| **Home & errands** | Groceries, shopping, chores, repairs, appliances, vehicle, pets, household info. |

### 3.3 Health

**Definition:** your body and mind, plus the medical needs of people you care for.

| | |
|---|---|
| Belongs | Medicines, pill schedules, refills; doctor, dentist and lab visits, symptoms, checkups (yours or family's); workouts, sport routines, diet, sleep; stress, therapy, meditation, personal reflection and journaling |
| Not here | Paying gym or insurance bills (Money & home). Pet vet visits (Money & home). Cooking for fun (Fun & interests). |
| **Medicines & doctors** | Pills, doses, refills, appointments, tests, checkups, prescriptions. |
| **Fitness & food** | Workouts, sports routines, steps, sleep, diet and nutrition goals. |
| **Mind & mood** | Feelings, stress, therapy, meditation, journaling, faith or reflection practice. |

### 3.4 People

**Definition:** your relationships and the occasions you share.

| | |
|---|---|
| Belongs | Family, partner, friends; calls and messages to make; kids' school and care; birthdays, anniversaries, weddings, dates, parties, gifts, invitations; community and religious gatherings |
| Not here | Medical care for a family member (Health). A trip with friends (Fun & interests). College events you organise (Learning & work). |
| **Family** | Parents, siblings, spouse, kids: their needs, school, family plans. |
| **Friends & partner** | Friends, boyfriend/girlfriend, catch-ups, people to call or message. |
| **Occasions & gifts** | Birthdays, anniversaries, weddings, dates, parties, gatherings, gifts, invites. |

### 3.5 Fun & interests

**Definition:** what you do for enjoyment and curiosity.

| | |
|---|---|
| Belongs | Shows, films, books, podcasts, music, videos to watch later; quotes and highlights you liked; recipes to try, cooking, games, crafts, photography and other hobbies; holidays, trip plans and bookings, visas for a trip, packing; places and restaurants to try |
| Not here | Study or work material (Learning & work). Diet plans (Health). Weekly groceries (Money & home). Work trips (Learning & work). |
| **Watch, read & listen** | Your media queue, plus quotes and highlights from it. |
| **Cooking & hobbies** | Recipes to try, cooking ideas, games, crafts, creative pursuits. |
| **Trips & places** | Holidays, itineraries, bookings, trip visas, packing, places to visit. |

### 3.6 Why this set is complete and does not overlap

**Complete.** Every top-level domain in the frameworks above lands in one of the five:

| Category | WHOQOL [2] | OECD [4] | PWI [5] | Wheel of Life [7] | ATUS [11] |
|---|---|---|---|---|---|
| Learning & work | Work capacity; new information and skills; thinking and learning | Work and job quality; knowledge and skills | Achieving in life | Mental and education; (financial and) career | Working; educational activities |
| Money & home | Financial resources; home environment; transport; safety | Income and wealth; housing | Standard of living; future security | Financial (and career); (family and) home | Household activities; purchasing goods and services |
| Health | Physical; psychological; level of independence (medication); personal beliefs | Health; subjective well-being | Health | Physical and health; spiritual and ethical (personal practice) | Personal care; sports and exercise |
| People | Social relationships | Social connections; civic engagement | Relationships; community-connectedness | Family (and home); social (and cultural) | Caring for household and nonhousehold members; socializing; civic and religious |
| Fun & interests | Recreation and leisure | Work-life balance (leisure time) | none | (Social and) cultural | Leisure and sports |

Environment quality and personal safety rarely appear in notes. If they do: home security goes to Money & home, and personal worries go to Health › Mind & mood.

**Non-overlapping.** Real life overlaps; a gym fee is both money and health. The frameworks overlap too: WHO merged its six domains into four [2]. Overlap is settled by the **fixed priority order in §4**, so every note gets exactly one category.

**Explicit answers:**

| Question | Answer and reason |
|---|---|
| Is a "Personal / Reference" catch-all needed? | **No.** "Reference" is a role found in 47% of coded notes [17], so a Reference category would duplicate half the inbox. Reference items go by area: wifi details → Home & errands; IDs → Bank, tax & documents; journaling → Mind & mood; quotes → Watch, read & listen. Truly unclear notes stay in **Needs you**, which is an inbox state, not a category. Catch-alls attract low-confidence AI guesses. |
| Should Travel be top-level? | **No; make it a subcategory (Trips & places).** No wellbeing framework has a travel domain. Time-use standards file travel under its purpose [12][13]. In PARA a trip is a project, not an area [8]. Cortana users treat bookings and passport renewal as chores [14]. Work trips go to Work & career, and passport renewal goes to Bank, tax & documents. |
| Where do work and study go? | **Together, in Learning & work**, with Study and Work & career as separate subcategories. ICATUS counts job-related study as employment [13]. For a student, college duties (events, admin) behave like work. Merging keeps the set at five. |
| Where do home, household and chores go? | **Money & home.** ATUS household activities include "filling out paperwork" [12]. WHOQOL's Environment domain groups home and finances [2]. Cortana's "Chores" mixes laundry with paying rent [14]. The Wheel of Life pairs home with family instead [7]. We do not follow it, because home notes are mostly logistics (bills, repairs, groceries), not relationships. |
| Where do hobbies, ideas, creativity, recipes and entertainment go? | **Fun & interests**, with three exceptions decided by purpose: build or career ideas (app or startup) → Learning & work › Skills & projects; a diet → Health › Fitness & food; routine meals and groceries → Money & home › Home & errands. |
| Family and friends vs events? | **People** holds both. Events centred on a person (birthday, wedding, date) → People › Occasions & gifts. Events centred on an activity go by activity: a concert → Fun; a college fest you organise → Learning & work. A date or time on a note never decides the category; it feeds reminders. |

---

## 4. Boundary rules for ambiguous notes *(analysis)*

Apply in order and stop at the first rule that fires.

| # | Rule | Why |
|---|---|---|
| R1 | **Health data → Health.** Any medicine, symptom, test, therapy or clinician appointment, including for family members. | Health data is a special category (GDPR Art. 9, India's DPDP Act) and the Health bot is consent-gated (design §8.5). WHOQOL treats medication dependence as a health facet [2]. |
| R2 | **Obligations and paperwork for your own money → Money & home.** Paying a bill, fee or dues; starting, renewing or cancelling a subscription or membership; tax, bank, insurance, IDs. *One-off purchases that serve a plan do not count* (gift, ingredients, trip booking); those go to R3. | One place for "what do I owe". Cortana users file these as chores [14]. |
| R3 | **The purpose the user states beats the source's content.** "for Statistics", "for my date", "for the Goa trip". | PARA: organise by the goal it serves [8]. Users append purpose words to notes [16]. |
| R4 | **Whose responsibility?** An organisation's money or tasks (college, employer, club) → Learning & work. Your child's school → People › Family. | ATUS codes children's homework help and events as childcare [12]. |
| R5 | **Otherwise the topic decides, not the format.** A video, PDF or link is only a container. | Notes don't fit PIM data types [16]. Formats cut across roles [17]. |
| R6 | **Still tied, or confidence low → don't guess.** Hold the note in **Needs you** with the top two choices. The user's pick becomes a memory example. | Malone: categorising is cognitively hard, so automate what you can [20]. Corrections are the strongest memory source (design §8.2). |

**Worked examples**

| Note | Result | Rule |
|---|---|---|
| College Halloween event budget ("talk to Admin team about budget") | Learning & work › Study | R4: the college's money, not yours |
| Pasta recipe "for my date on Saturday" | People › Occasions & gifts | R3: stated purpose. *Counterpoint:* ATUS would code the cooking as household [12]. We follow purpose so the plan sits with the date. |
| "Pay gym membership ₹2,500 by 1 Dec" | Money & home › Bills & subscriptions | R2. ("New gym plan: push/pull/legs" → Health › Fitness & food.) |
| "Doctor in Manali for ear pain, 28 Dec" (during a trip) | Health › Medicines & doctors | R1; it shows up next to the trip through dates and tags. |
| "Buy Priya's birthday gift" | People › Occasions & gifts | R2 excludes one-off purchases → R3 |
| "Pay semester fee ₹45,000 by 10 Dec" | Money & home › Bills & subscriptions | R2 (tag: college) |
| "Flight to Pune for client meeting" | Learning & work › Work & career | R3 |
| "Pick up Dad's prescription" | Health › Medicines & doctors | R1, even though it is an errand |

---

## 5. Mapping test *(analysis)*

The owner's real notes are #1 to #8. "Flag" marks a note that could plausibly fit two categories.

| # | Note | Category | Subcategory | Rule | Reason |
|---|---|---|---|---|---|
| 1 | "I need to give Python quiz tomorrow at 11:00am" | Learning & work | Study | R5 | Graded course test; the time feeds reminders |
| 2 | "Cancel Netflix subscription on 15th December 2026" | Money & home | Bills & subscriptions | R2 | **Flag.** Netflix is entertainment, but the action is cancelling a subscription |
| 3 | Butter chicken recipe (YouTube): "I'll make it someday" | Fun & interests | Cooking & hobbies | R3 | Purpose: cook for enjoyment, no occasion |
| 4 | White sauce pasta recipe (YouTube): "for my date on coming Saturday" | People | Occasions & gifts | R3 | **Flag.** Content says cooking; stated purpose (date) wins |
| 5 | Screenshot of college Halloween event budget mail: "talk to Admin team of my college about budget" | Learning & work | Study | R4 | **Flag.** Mentions money, but it is the college event's budget |
| 6 | Hypothesis Testing practice PDF: "for Statistics" | Learning & work | Study | R3 | Stated course |
| 7 | YouTube video on an AI coding agent (Nemotron), no note | Learning & work | Skills & projects | R5 | **Flag.** No purpose given; topic is a coding tool and persona memory says "learning Python". At low confidence → R6 (alternative: Fun › Watch, read & listen) |
| 8 | "Pill reminder": when to take what pills | Health | Medicines & doctors | R1 | Medicine schedule |
| 9 | "Electricity bill ₹1,840 due 20 Nov" | Money & home | Bills & subscriptions | R2 | Bill |
| 10 | "Pay rent to landlord by 5th" | Money & home | Bills & subscriptions | R2 | Recurring payment |
| 11 | "Health insurance renews 3 Jan, compare plans" | Money & home | Bank, tax & documents | R2 | **Flag.** Says "health" but has no medical detail; it is a financial policy |
| 12 | "Buy Crocin and cough syrup" | Health | Medicines & doctors | R1 | Medicine, even though it is a purchase |
| 13 | "Leg day: squats 4×10, lunges 3×12" | Health | Fitness & food | R5 | Workout |
| 14 | "Therapy Thursday 6 pm, talk about exam stress" | Health | Mind & mood | R1 | **Flag.** Mentions exams; therapy wins |
| 15 | "Groceries: milk, eggs, atta, onions" | Money & home | Home & errands | R5 | Household supplies |
| 16 | "Kitchen tap leaking, call plumber" | Money & home | Home & errands | R5 | Home repair (ATUS household activity [12]) |
| 17 | "Aarav's parent-teacher meeting at school, Fri 10 am" | People | Family | R4 | **Flag.** "School", but it is your child's, not your study |
| 18 | "Mom's thyroid checkup on 12th, book lab test" | Health | Medicines & doctors | R1 | **Flag.** Family member; health data goes to the consent-gated bot (tag: Mom) |
| 19 | "Ankit's wedding in Jaipur 14 Dec: buy outfit, book train" | People | Occasions & gifts | R3 | **Flag.** Has travel and shopping; the purpose is the wedding |
| 20 | "Priya's birthday 9 Nov, order a gift" | People | Occasions & gifts | R3 | One-off purchase for an occasion |
| 21 | "Goa trip with college friends 26–29 Dec: book hostel" | Fun & interests | Trips & places | R5 | **Flag.** Friends are involved, but the trip is the point |
| 22 | "Thailand visa appointment 8 Jan" | Fun & interests | Trips & places | R3 | **Flag.** A document task, but it serves one trip |
| 23 | "Passport expires Mar 2027, renew" | Money & home | Bank, tax & documents | R2 | The ID outlives any single trip |
| 24 | "Flight DEL→GOI 26 Dec 06:10, PNR …" | Fun & interests | Trips & places | R3 | Part of the Goa trip (a work flight → Work & career) |
| 25 | "Read *Atomic Habits*" | Fun & interests | Watch, read & listen | R5 | Personal reading (a course text → Study) |
| 26 | "Podcast: Freakonomics episode on tipping" | Fun & interests | Watch, read & listen | R5 | Curiosity listening |
| 27 | "Watch *Panchayat* S4 on Prime" | Fun & interests | Watch, read & listen | R5 | Watching is fun; paying or cancelling is money (compare #2) |
| 28 | "'We suffer more in imagination than in reality' (Seneca)" | Fun & interests | Watch, read & listen | R5 | **Flag.** Kept for personal value [17]; if saved for coping → Mind & mood |
| 29 | "App idea: split-bill app that reads UPI SMS" | Learning & work | Skills & projects | R5 | Something to build |
| 30 | "Startup idea: tiffin subscription for hostel students" | Learning & work | Skills & projects | R5 | Venture idea |
| 31 | "Home wifi password (router sticker)" | Money & home | Home & errands | R5 | Household info |
| 32 | "Google interview round 2 Tue, revise DSA" | Learning & work | Work & career | R3 | **Flag.** "Revise" sounds like study; the purpose is a job interview |
| 33 | "Salary credited, move ₹5,000 to RD" | Money & home | Bank, tax & documents | R2 | Your own money (a salary negotiation → Work & career) |
| 34 | "File ITR before 31 July" | Money & home | Bank, tax & documents | R2 | Tax |
| 35 | "Car service due at 10,000 km, book slot" | Money & home | Home & errands | R5 | Vehicle upkeep (ATUS household activity [12]) |
| 36 | "Bruno's rabies shot at the vet, 18 Nov" | Money & home | Home & errands | R5 | **Flag.** Sounds medical, but Health is for people; pet care is household [12] |
| 37 | "Felt low after mid-sem result, need to talk to someone" | Health | Mind & mood | R1 | **Flag.** Mentions exams; it is about how you feel |

**Result:** all 37 notes land in exactly one category. 15 were flagged and every flag is settled by R1 to R5. None needs a catch-all, and only #7 may go to Needs you at low confidence. Spread: Money & home 12, Fun & interests 8, Learning & work 7, Health 6, People 4.

---

## 6. Notes for the product *(analysis)*

### 6.1 Mapping onto the five existing bots (design §4.1)

| Current bot | New bot | Change |
|---|---|---|
| Learning and work | **Learning & work** | Keep. Topics become Study (› Python, › Statistics), Work & career, Skills & projects. |
| Money and admin | **Money & home** | Rename. "Money and admin" becomes Bills & subscriptions plus Bank, tax & documents. "Shopping and errands" becomes Home & errands and also takes chores, repairs, car, pets and household info. |
| Health | **Health** | Keep; scope widens to mind. "Pill reminder" becomes a subtopic of Medicines & doctors. |
| Travel | **Fun & interests** | Repurpose the slot. Travel becomes the Trips & places topic and keeps its extraction (trip dates, bookings, documents, packing). New topics: Watch, read & listen and Cooking & hobbies. |
| Social and personal | **People** | Rename and drop "personal". "People" becomes Family, Friends & partner, Occasions & gifts. "Cooking ideas" moves to Fun & interests › Cooking & hobbies. "Personal and reference" is dissolved: re-file its items by area, and send unclear ones to Needs you. |

The bot count stays at five. Renaming bots and moving topics on real databases needs an Alembic data migration (AGENTS.md).

### 6.2 Suggested "about" text for each bot (feeds the AI)

- **Learning & work:** "Things the user studies, earns a living from, or is building skills for: classes, quizzes, exams, assignments, study material, college admin and clubs or events they help run, jobs, internships, interviews, meetings, work trips, side projects, and app or startup ideas. Not here: paying course fees (Money & home), leisure reading or videos (Fun & interests), a child's school (People)."
- **Money & home:** "Running the user's household and their own money: rent, bills, EMIs, subscriptions and memberships (paying, renewing, cancelling), fees, bank, salary received, savings, tax, insurance, IDs such as passport or licence, warranties, groceries, shopping, chores, repairs, appliances, car, pets, and household info. Not here: a college's or employer's budget (Learning & work), gifts for someone (People), bookings for a specific trip (Fun & interests), medicines (Health)."
- **Health:** "The user's body and mind, and medical needs of people they care for: medicines and pill schedules, refills, doctor, dentist and lab visits, symptoms, checkups, workouts, sports routines, diet, sleep, stress, therapy, meditation, and personal reflection or journaling. Not here: paying gym or insurance bills (Money & home), pet vet visits (Money & home), recipes to try for fun (Fun & interests)."
- **People:** "The user's relationships and shared occasions: family, partner, friends, calls or messages to make, kids' school and care, birthdays, anniversaries, weddings, dates, parties, gifts, invitations, and community or religious gatherings. Not here: medical care for a family member (Health), trips with friends (Fun & interests), events the user organises for college or work (Learning & work)."
- **Fun & interests:** "What the user does for enjoyment and curiosity: shows, films, books, podcasts, music, videos to watch later, quotes they liked, recipes to try, cooking, games, crafts and other hobbies, holidays, trip plans and bookings, visas for a trip, packing, and places or restaurants to visit. Not here: study or work material (Learning & work), diet plans (Health), weekly groceries (Money & home), work trips (Learning & work)."

### 6.3 Other implications

- **Put R1 to R6 in Captain's routing prompt verbatim**, and log which rule fired as the filing "reason". This makes corrections explainable.
- **Keep time as a lens, not a category.** Dates feed Today, Upcoming and briefings across all bots (design §6 and §7). A note never goes to a bot just because it has a date.
- **Health consent text should say it covers family members' medical notes**, because R1 routes them there.
- **Credentials:** notes like wifi passwords are secrets. Consider masking them in the UI and leaving them out of AI prompts.
- **Watch the spread.** If a user's Trips & places or Cooking & hobbies topic grows much larger than its siblings, that is evidence for a new bot later. That would be a user-added extra, not a sixth default.

---

## Facts not verified in first-party sources

- **Wheel of Life origin:** attribution to Paul J. Meyer and a 1960s date appears only in secondary coaching sites. The SMI page confirms the six areas but not the author or date [7].
- **PWI spiritual domain optional since 2013:** secondary search snippets only [6]. The manual PDF download from acqol.com.au failed.
- **Malone 1983, Bellotti 2004, Bergman 2008, Dai 2005, Lin 2004:** full texts were not opened because of the ACM bot check. Only the authors' abstracts were read via OpenAlex. Bellotti's "11.25 tools" comes from Bernstein et al. [15].
- **Jones's "six senses" of personal information** (owned by, about, directed to, sent by, experienced by, relevant to me): seen only via Wikipedia *(secondary)* [27]; not used as evidence above.
- **No large content analysis of modern smartphone notes apps** (Apple Notes, Google Keep) was found. Apple and Google do not document list or notes categories.
- **Generalisability:** the Cortana data covers US users only, from 2015, and time-based reminders only [14]. List-it users skewed towards Firefox users and readers of tech press [17]. The information-scraps sample was knowledge workers [15]. ATUS covers the US. Applying these to an Indian student user is an assumption.

## Sources

1. https://www.who.int/tools/whoqol: WHO, "WHOQOL: Measuring Quality of Life"
2. https://www.who.int/publications/i/item/WHO-HIS-HSI-Rev.2012.03: WHO (2012), "The World Health Organization Quality of Life (WHOQOL)", WHO/HIS/HSI Rev.2012.03 (PDF: https://iris.who.int/server/api/core/bitstreams/4c5cd94a-599e-450f-9141-4a21a7b74849/content); Table 1.4, Chapter 5
3. https://www.oecd.org/en/data/tools/well-being-data-monitor.html: OECD Well-being Data Monitor (framework of 11 dimensions; BLI FAQ, "updated in 2025")
4. https://www.oecd.org/en/data/tools/well-being-data-monitor/current-well-being.html: OECD "Current well-being" dashboard (embedded app: https://oecd-main.shinyapps.io/cwb_page/)
5. https://acqol.com.au/resources/personal-wellbeing-index/: Australian Centre on Quality of Life (Deakin), "Personal Wellbeing Index"
6. *(Secondary)* https://novopsych.com/assessments/well-being/personal-wellbeing-index-adult-5-pwi-a/: NovoPsych, "PWI-A" (citing International Wellbeing Group 2013/2024 manual; spiritual item optional). Not verified.
7. http://www.lmi-world.com/smi/: Success Motivation International, "Wheel of Life® Assessment" / The Total Person
8. https://fortelabs.com/blog/para/: Tiago Forte, "The PARA Method" (published Feb 24, 2023)
9. https://gettingthingsdone.com/2011/01/the-6-horizons-of-focus/: David Allen, "The 6 Horizons of Focus" (2011)
10. https://gettingthingsdone.com/wp-content/uploads/2014/10/2016-Levels-of-Your-Work.pdf: David Allen Company, "Horizons of Focus: The Altitude Map" (PDF, 2015)
11. https://www.bls.gov/news.release/atus.t01.htm: BLS, ATUS 2025 Results, Table 1 (released June 25, 2026); summary: https://www.bls.gov/news.release/atus.nr0.htm
12. https://www.bls.gov/news.release/atus.tn.htm: BLS, "American Time Use Survey Technical Note" (2025 results)
13. https://unstats.un.org/unsd/demographic-social/time-use/icatus-2016/tableview/: UN Statistics Division, ICATUS 2016 (table view)
14. https://graus.nu/blog/wp-content/papercite-data/pdf/graus2016analyzing.pdf: Graus, Bennett, White, Horvitz (2016), "Analyzing and Predicting Task Reminders", UMAP '16, DOI 10.1145/2930238.2930239; MSR page: https://www.microsoft.com/en-us/research/publication/analyzing-predicting-task-reminder/
15. https://people.csail.mit.edu/msbernst/papers/TOIS-final-with-refs.pdf: Bernstein, Van Kleek, Karger, schraefel (2008), "Information Scraps: How and Why Information Eludes Our Personal Information Management Tools", ACM TOIS 26(4), https://doi.org/10.1145/1402256.1402263
16. https://people.csail.mit.edu/msbernst/papers/note1546-vankleek.pdf: Van Kleek, Bernstein, Panovich, Vargas, Karger, schraefel (2009), "Note to Self: Examining Personal Information Keeping in a Lightweight Note-Taking Tool", CHI '09, https://doi.org/10.1145/1518701.1518924
17. https://people.csail.mit.edu/emax/papers/chi2011-finders-keepers.pdf: Van Kleek, Styke, schraefel, Karger (2011), "Finders/keepers: A Longitudinal Study of People Managing Information Scraps in a Micro-note Tool", CHI '11, https://doi.org/10.1145/1978942.1979374 (DSpace: http://hdl.handle.net/1721.1/73002)
18. https://doi.org/10.1145/1056808.1056906: Dai, Lutters, Bower (2005), "Why use memo for all? Restructuring mobile applications to support informal note taking", CHI EA '05 *(abstract only, via https://api.openalex.org/works/doi:10.1145/1056808.1056906)*
19. https://doi.org/10.1145/985692.985779: Lin, Lutters, Kim (2004), "Understanding the micronote lifecycle", CHI '04 *(abstract only, via OpenAlex)*
20. https://doi.org/10.1145/357423.357430: Malone (1983), "How do people organize their desks? Implications for the design of office information systems", ACM TOOIS 1(1) *(abstract only, via https://api.openalex.org/works/doi:10.1145/357423.357430)*
21. https://homepages.cwi.nl/~steven/sigchi/bulletin/1995.3/barreau.html: Barreau & Nardi (1995), "Finding and Reminding: File Organization from the Desktop", SIGCHI Bulletin 27(3)
22. https://doi.org/10.1145/1402256.1402259: Bergman, Beyth-Marom, Nachmias, Gradovitch, Whittaker (2008), "Improved search engines and navigation preference in personal information management", ACM TOIS 26(4) *(abstract only, via https://api.openalex.org/works/doi:10.1145/1402256.1402259)*
23. https://mitpress.mit.edu/9780262035170/the-science-of-managing-our-digital-stuff/: Bergman & Whittaker (2016), *The Science of Managing Our Digital Stuff*, MIT Press
24. https://booksite.elsevier.com/samplechapters/9780123708663/Sample_Chapters/01~Front_Matter.pdf: Jones (2007), *Keeping Found Things Found*, Morgan Kaufmann (front matter and preface); book page: https://www.sciencedirect.com/book/9780123708663/keeping-found-things-found
25. https://doi.org/10.1145/985692.985785: Bellotti, Dalal, Good, Flynn, Bobrow, Ducheneaut (2004), "What a to-do: studies of task management towards the design of a personal task list manager", CHI '04 *(abstract only)*; listing: https://www.ischool.berkeley.edu/research/publications/2004/what-do-studies-task-management-towards-design-personal-task-list-manager
26. https://discovery.ucl.ac.uk/16608/1/16608.pdf: Blandford & Green (2001), "Group and Individual Time Management Tools: What You Get is Not What You Need", Personal and Ubiquitous Computing 5, https://doi.org/10.1007/PL00000020
27. *(Secondary)* https://en.wikipedia.org/wiki/Personal_information_management: Wikipedia, "Personal information management" (Jones's six senses). Not verified against Jones's own text.

Life Inbox context is from `docs/design/life-inbox-v2-design.md` §4 (bots) and §8 (memory and health consent).
