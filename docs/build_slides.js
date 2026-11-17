// DriveShare slides – "human" version: plain-language titles, first-person voice,
// fewer bullets, a short story arc, speaker notes on every slide. Black and white.
const pptxgen = require('pptxgenjs');
const sharp = require('sharp');
const fs = require('fs'), path = require('path');
const { applyTheme } = require('./apply_theme.js') /* pptx skill helper; optional */;
const D = __dirname + '/';
const OUT = D + 'DriveShare_Presentation.pptx';
const THEME = { name: 'DriveShare Mono', headFontFace: 'Arial', bodyFontFace: 'Calibri',
  colors: { dk1: '000000', lt1: 'FFFFFF', dk2: '000000', lt2: 'F2F2F2', accent1: '000000', accent2: '404040',
            accent3: '595959', accent4: '7F7F7F', accent5: 'BFBFBF', accent6: '595959', hlink: '000000', folHlink: '404040' } };
const NAME = 'Dheyaa Alrabeei';

(async () => {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_WIDE';
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  pres.title = 'DriveShare – Term Project';
  pres.author = NAME;
  const C = pres.SchemeColor;

  pres.defineSlideMaster({ title: 'DARK', background: { color: C.text2 },
    objects: [
      { placeholder: { options: { name: 'title', type: 'title', x: 0.8, y: 2.2, w: 11.7, h: 1.4, fontSize: 54, bold: true, color: C.background1, valign: 'bottom', align: 'left' }, text: '' } },
      { placeholder: { options: { name: 'body', type: 'body', x: 0.8, y: 3.75, w: 11.7, h: 1.8, fontSize: 22, color: C.accent5, valign: 'top', align: 'left' }, text: '' } },
    ] });
  pres.defineSlideMaster({ title: 'CONTENT', background: { color: C.background1 },
    objects: [
      { placeholder: { options: { name: 'title', type: 'title', x: 0.6, y: 0.4, w: 12.1, h: 0.9, fontSize: 32, bold: true, color: C.text2, valign: 'middle', align: 'left', margin: 0 }, text: '' } },
      { text: { text: 'DriveShare · ' + NAME, options: { x: 0.6, y: 7.0, w: 8, h: 0.3, fontSize: 10, color: C.accent6, margin: 0 } } },
    ],
    slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent6, align: 'right' } });

  // ---------- helpers ----------
  const img = async (slide, file, box) => {
    const gray = require('os').tmpdir() + '/driveshare-bw/' + file;
    fs.mkdirSync(path.dirname(gray), { recursive: true });
    await sharp(D + file).grayscale().toFile(gray);
    const m = await sharp(gray).metadata();
    const r = Math.min(box.w / m.width, box.h / m.height);
    const w = m.width * r, h = m.height * r;
    slide.addImage({ path: gray, x: box.x + (box.w - w) / 2, y: box.y + (box.h - h) / 2, w, h, altText: file });
  };
  const card = (slide, x, y, w, h, fill) => slide.addShape(pres.shapes.ROUNDED_RECTANGLE,
    { x, y, w, h, rectRadius: 0.12, fill: { color: fill || C.background2 }, line: { color: fill || C.background2 } });
  const chip = (slide, text, x, y, w) => {
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.38, rectRadius: 0.19, fill: { color: C.accent1 }, line: { color: C.accent1 } });
    slide.addText(text, { x, y, w, h: 0.38, fontSize: 12, bold: true, color: C.background1, align: 'center', valign: 'middle', margin: 0, isTextBox: true });
  };
  const text = (slide, t, x, y, w, h, o = {}) => slide.addText(t, { x, y, w, h, fontSize: 16, color: C.text1, margin: 0, valign: 'top', isTextBox: true, ...o });
  const label = (slide, t, x, y, w) => text(slide, t, x, y, w, 0.35, { fontSize: 13, bold: true, color: C.accent6, charSpacing: 1 });
  const bullets = (items) => items.map((t, i) => ({ text: t, options: { bullet: true, paraSpaceAfter: 10, breakLine: i < items.length - 1 } }));
  const add = (section, master = 'CONTENT') => pres.addSlide({ masterName: master, sectionTitle: section });
  const dot = (slide, n, x, y, d = 0.5) => {
    slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: C.accent1 }, line: { color: C.accent1 } });
    slide.addText(String(n), { x, y, w: d, h: d, fontSize: 15, bold: true, color: C.background1, align: 'center', valign: 'middle', margin: 0, isTextBox: true });
  };

  // ================= Intro =================
  pres.addSection({ title: 'Intro' });
  let s = add('Intro', 'DARK');
  s.addText('DriveShare', { placeholder: 'title' });
  s.addText([{ text: 'Rent a car from someone down the street', options: { breakLine: true } },
             { text: NAME + ' · CIS 476 Software Design · Term Project · Fall 2026', options: { fontSize: 16, color: C.background2 } }], { placeholder: 'body' });
  s.addNotes('Introduce yourself. DriveShare is a Turo-style app: people who own cars rent them out, people who need a car rent one directly from them.');

  s = add('Intro'); s.addText('What this video covers', { placeholder: 'title' });
  [['The demo', 'I use every feature as an owner and as a renter'], ['How it fits together', 'Flask, SQLite, and how the code is organized'],
   ['The six design patterns', 'What problem each one solves in DriveShare'], ['Two patterns up close', 'Observer and Chain of Responsibility, line by line'],
   ['Wrapping up', 'Database, tests, what was hard, what I would do next']].forEach(([h, d], i) => {
    const y = 1.6 + i * 1.02;
    dot(s, i + 1, 0.8, y, 0.7);
    text(s, h, 1.8, y - 0.02, 5.6, 0.4, { fontSize: 20, bold: true, color: C.text2 });
    text(s, d, 1.8, y + 0.38, 5.8, 0.35, { fontSize: 15, color: C.accent6 });
  });
  await img(s, 'screenshots/05_car_detail_quote.png', { x: 8.0, y: 1.5, w: 4.7, h: 5.2 });
  s.addNotes('Quick roadmap: demo first, then the design.');

  s = add('Intro'); s.addText('Why I built DriveShare', { placeholder: 'title' });
  text(s, 'Most cars spend most of the day parked.', 0.6, 1.6, 5.6, 1.5, { fontFace: 'Arial', fontSize: 30, bold: true, color: C.text2 });
  text(s, 'If you own one, it could be earning you money while it sits in the driveway.', 0.6, 3.25, 5.4, 0.9, { fontSize: 17 });
  text(s, 'If you need one for a weekend, you could borrow it from a neighbor instead of standing in line at a rental counter.', 0.6, 4.25, 5.4, 1.2, { fontSize: 17 });
  text(s, 'DriveShare connects those two people directly.', 0.6, 5.6, 5.4, 0.5, { fontSize: 17, bold: true });
  await img(s, 'screenshots/01_home.png', { x: 6.6, y: 1.5, w: 6.1, h: 5.3 });
  s.addNotes('Keep this short and conversational: the idea behind the app, in your own words.');

  // ================= Demo =================
  pres.addSection({ title: 'Demo' });
  s = add('Demo'); s.addText('What you can do in DriveShare', { placeholder: 'title' });
  const cols = [
    ['If you own a car', ['List it with its details and a calendar', 'Change the price or dates any time', 'Accept or decline booking requests', 'Get paid when the renter pays']],
    ['If you need a car', ['Search by place, dates, price and more', 'Watch a car and get told when it fits', 'Book it for the exact times you need', 'Pay with one click']],
    ['Both of you', ['Sign up with three security questions', 'Message each other', 'Get notifications and emails', 'See your history and review each other']],
  ];
  cols.forEach(([h, items], i) => {
    const x = 0.6 + i * 4.1;
    card(s, x, 1.55, 3.85, 5.15);
    text(s, h, x + 0.3, 1.8, 3.3, 0.5, { fontFace: 'Arial', fontSize: 20, bold: true, color: C.text2 });
    s.addText(bullets(items), { x: x + 0.3, y: 2.5, w: 3.35, h: 4.0, fontSize: 16, color: C.text1, valign: 'top', margin: 0, isTextBox: true });
  });
  s.addNotes('Every required feature is here, plus rental history and reviews, which were optional for solo projects.');

  s = add('Demo'); s.addText('The demo, step by step', { placeholder: 'title' });
  [['Sign up', 'with three security questions'], ['Alice lists a car', 'with a few extras and a calendar'],
   ['Bob searches', 'and the results update as he types'], ['Bob watches the Tesla', 'and gets a ping when Alice drops the price'],
   ['Bob books the Camry', 'and an overlapping booking is blocked'], ['Alice confirms, Bob pays', 'and both balances change'],
   ['They message and review', 'each other after the trip'], ['Carol forgets her password', 'and answers her questions to reset it']].forEach(([h, d], i) => {
    const y = 1.5 + i * 0.66;
    dot(s, i + 1, 0.6, y, 0.46);
    text(s, h, 1.25, y, 2.9, 0.46, { fontSize: 15, bold: true, color: C.text2, valign: 'middle' });
    text(s, d, 4.15, y, 3.1, 0.46, { fontSize: 14, valign: 'middle' });
  });
  await img(s, 'screenshots/13_notifications_renter.png', { x: 7.5, y: 1.6, w: 5.2, h: 5.0 });
  s.addNotes('Switch to the browser here and follow these steps.');

  // ================= Design =================
  pres.addSection({ title: 'Design' });
  s = add('Design'); s.addText('Architecture: how the pieces fit together', { placeholder: 'title' });
  await img(s, 'diagrams/architecture.png', { x: 0.6, y: 1.4, w: 12.1, h: 4.9 });
  text(s, 'Pages talk to thin routes. Routes hand the real work to services. Each design pattern lives in its own file.', 0.6, 6.4, 12.1, 0.45, { fontSize: 15, color: C.accent6, align: 'center' });
  s.addNotes('Three layers: the browser, routes.py, and the services. Patterns sit underneath in their own folder.');

  const patterns = [
    ['Singleton: one place that knows who\'s logged in', 'patterns/session_manager.py', 'diagrams/slides/singleton.png',
      'Every page needs to know who you are. If different parts of the app kept their own list of logins, they could disagree, and logging out might not work everywhere.',
      'SessionManager can only ever exist once. It hands out random login tokens, keeps only a scrambled copy of each, logs you out after 30 idle minutes, and signs you out everywhere after a password reset.'],
    ['Builder: a car listing, one piece at a time', 'patterns/car_builder.py', 'diagrams/slides/builder.png',
      'A listing has 6 must-have details and 8 optional ones. A constructor with 14 arguments is hard to read and easy to get wrong.',
      'CarListingBuilder lets the form set one detail at a time and checks each one as it goes. It only hands back a finished listing when nothing required is missing.'],
    ['Observer: alerts when a watched car fits', 'patterns/observer.py', 'diagrams/slides/observer.png',
      'Renters want to hear when a car drops to their price or frees up for their dates. But the code that changes a car shouldn\'t need to know who is waiting.',
      'Each watch is an observer of the car. When the price or calendar changes, the car announces it, and every watch checks its own conditions before sending a notification.'],
    ['Mediator: keeping the page\'s widgets in sync', 'static/js/mediator.js', 'diagrams/slides/mediator.png',
      'On the car page, changing a date affects the price, the Book button and the watch form. Wiring every widget to every other widget gets messy fast.',
      'Each widget only talks to a mediator. The mediator decides who needs to react, so adding a new widget means changing one place.'],
    ['Proxy: a bouncer in front of payments', 'patterns/payment_proxy.py', 'diagrams/slides/proxy.png',
      'Nobody should be able to pay for someone else\'s booking, pay twice, or change the amount in the browser.',
      'PaymentProxy looks exactly like the payment gateway, but first checks who you are, the booking, the amount and your balance. Only then does the payment go through.'],
    ['Chain of Responsibility: checks before a reset', 'patterns/password_recovery.py', 'diagrams/slides/chain.png',
      'Resetting a password takes several checks in a row, and any one of them should be able to stop it.',
      'Each check is its own link: a lockout check, one link per security question, then the reset. A request moves down the chain until a link says no.'],
  ];
  for (const [title, file, diagram, problem, solution] of patterns) {
    s = add('Design'); s.addText(title, { placeholder: 'title' });
    const meta = await sharp(D + diagram).metadata();
    if (meta.width / meta.height > 2.2) {
      // wide diagram: text in two columns on top, diagram across the full width
      chip(s, file, 0.6, 1.45, 3.6);
      label(s, 'THE PROBLEM', 0.6, 2.05, 5.8);
      text(s, problem, 0.6, 2.4, 5.8, 1.25);
      label(s, 'WHAT I DID', 6.9, 2.05, 5.8);
      text(s, solution, 6.9, 2.4, 5.8, 1.25);
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 3.8, w: 12.1, h: 3.0, rectRadius: 0.12, fill: { color: 'FFFFFF' }, line: { color: 'BFBFBF', width: 1 } });
      await img(s, diagram, { x: 0.75, y: 3.9, w: 11.8, h: 2.8 });
    } else {
      // squarer diagram: text on the left, big diagram on the right
      chip(s, file, 0.6, 1.5, 3.6);
      label(s, 'THE PROBLEM', 0.6, 2.2, 4.3);
      text(s, problem, 0.6, 2.55, 4.3, 1.8);
      label(s, 'WHAT I DID', 0.6, 4.45, 4.3);
      text(s, solution, 0.6, 4.8, 4.3, 2.0);
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.2, y: 1.45, w: 7.5, h: 5.4, rectRadius: 0.12, fill: { color: 'FFFFFF' }, line: { color: 'BFBFBF', width: 1 } });
      await img(s, diagram, { x: 5.35, y: 1.55, w: 7.2, h: 5.2 });
    }
    s.addNotes('Explain the problem first, then how the pattern fixes it. Point at the diagram.');
  }

  // ================= Code =================
  pres.addSection({ title: 'Code' });
  const code = (title, file, snippet, notes, speaker) => {
    s = add('Code'); s.addText(title, { placeholder: 'title' });
    chip(s, file, 0.6, 1.5, 3.6);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 2.1, w: 7.6, h: 4.7, rectRadius: 0.1, fill: { color: C.text2 }, line: { color: C.text2 } });
    s.addText(snippet, { x: 0.85, y: 2.25, w: 7.2, h: 4.45, fontFace: 'Courier New', fontSize: 12, color: 'FFFFFF', valign: 'top', margin: 0, isTextBox: true });
    label(s, 'IN PLAIN WORDS', 8.6, 2.1, 4.1);
    s.addText(bullets(notes), { x: 8.6, y: 2.5, w: 4.1, h: 4.3, fontSize: 16, color: C.text1, valign: 'top', margin: 0, isTextBox: true });
    s.addNotes(speaker);
  };
  code('A closer look: Observer', 'patterns/observer.py',
`class WatchObserver(CarObserver):
    def criteria_met(self, car):
        max_price = self.watch.get("max_price")
        if max_price is not None and \\
           car["price_per_day"] > max_price:
            return False
        start, end = self.watch["start_time"], ...
        if start and not self._is_available(
                car["id"], start, end):
            return False
        return True

    def update(self, car, event):
        if self.criteria_met(car):
            self._notifier(self.watch["renter_id"],
                           "watch", message, link)

class CarListingSubject:
    def notify_observers(self, event):
        for observer in list(self._observers):
            observer.update(self.car, event)`,
    ['When Alice lowers her price, the car announces it', 'Each watch asks: is it cheap enough, and are my dates free?', 'Only a yes to everything sends Bob a message', 'The listing code never knows Bob is watching'],
    'Open observer.py in VS Code and walk through criteria_met, update, and notify_observers.');
  code('A closer look: Chain of Responsibility', 'patterns/password_recovery.py',
`class RecoveryHandler(ABC):
    def set_next(self, handler):
        self._next = handler
        return handler            # enables chaining

    def handle(self, request):
        result = self.check(request)
        if result is not None:    # this link says no
            return result
        if self._next is None:
            return RecoveryResult(True, "reset")
        return self._next.handle(request)

def build_recovery_chain(db, on_reset=None):
    head = AccountLockoutHandler(db)
    (head.set_next(SecurityQuestionHandler(db, 1))
         .set_next(SecurityQuestionHandler(db, 2))
         .set_next(SecurityQuestionHandler(db, 3))
         .set_next(PasswordResetHandler(db, on_reset)))
    return head`,
    ['Every link runs the same handle() method', 'Each link only answers one question', 'Any link can stop the reset', 'Adding an email code later means adding one class'],
    'Open password_recovery.py and walk through handle(), then build_recovery_chain().');

  // ================= Wrap-up =================
  pres.addSection({ title: 'Wrap-up' });
  s = add('Wrap-up'); s.addText('Database: where everything lives', { placeholder: 'title' });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.45, w: 8.5, h: 5.4, rectRadius: 0.12, fill: { color: 'FFFFFF' }, line: { color: 'BFBFBF', width: 1 } });
  await img(s, 'diagrams/slides/er.png', { x: 0.75, y: 1.55, w: 8.2, h: 5.2 });
  label(s, 'A FEW RULES THE DATABASE ENFORCES', 9.3, 1.6, 3.4);
  s.addText(bullets(['A booking can only be paid once', 'Each person reviews a rental once', 'No overlapping bookings for the same car', 'Passwords and answers are stored scrambled']),
    { x: 9.3, y: 2.1, w: 3.4, h: 4.6, fontSize: 15, color: C.text1, valign: 'top', margin: 0, isTextBox: true });
  s.addNotes('Ten tables in SQLite. Point out bookings, watches and payments.');

  s = add('Wrap-up'); s.addText('Correctness and testing: how I know it works', { placeholder: 'title' });
  [['19', 'automated tests', 'They all pass, and they cover every pattern'], ['2', 'layers stop double booking', 'The app checks, and the database checks again'], ['6', 'design patterns', 'Each in its own file, matching the diagrams']].forEach(([n, l, d], i) => {
    const x = 0.6 + i * 4.1;
    card(s, x, 1.6, 3.8, 2.7);
    text(s, n, x + 0.3, 1.75, 3.2, 1.2, { fontFace: 'Arial', fontSize: 64, bold: true, color: C.accent1 });
    text(s, l, x + 0.3, 2.95, 3.2, 0.45, { fontSize: 18, bold: true, color: C.text2 });
    text(s, d, x + 0.3, 3.4, 3.2, 0.75, { fontSize: 14, color: C.accent6 });
  });
  text(s, 'What happens if two people click "Book" at the same moment?', 0.6, 4.7, 12.1, 0.5, { fontSize: 18, bold: true, color: C.text2 });
  text(s, 'The first one locks the database, checks for overlaps, saves the booking and unlocks. The second one then checks, sees the first booking, and gets a polite "already booked". And if my code ever forgot to check, a rule inside the database would still refuse the second booking.',
    0.6, 5.25, 12.1, 1.3, { fontSize: 15 });
  s.addNotes('Run python -m pytest -q in the terminal to show 19 passed.');

  s = add('Wrap-up'); s.addText('What was hard', { placeholder: 'title' });
  [['Two people booking at once', 'Checking for overlaps and saving the booking had to happen as one locked step, or two renters could both "win". I added a database rule as a backup.'],
   ['Keeping the patterns testable', 'I wanted to test the patterns without starting the web server, so I passed the database work in as functions instead of hard-coding it.'],
   ['Making alerts feel live', 'There is no real-time server, so the bell quietly checks for news every few seconds and pops up a message when something new arrives.']].forEach(([h, d], i) => {
    const x = 0.6 + i * 4.1;
    card(s, x, 1.6, 3.8, 3.6);
    dot(s, i + 1, x + 0.3, 1.9);
    text(s, h, x + 0.3, 2.65, 3.2, 0.8, { fontFace: 'Arial', fontSize: 19, bold: true, color: C.text2 });
    text(s, d, x + 0.3, 3.5, 3.2, 2.5, { fontSize: 15 });
  });
  s.addNotes('Talk about these honestly; this is where you show what you learned.');

  s = add('Wrap-up'); s.addText('What I would do next', { placeholder: 'title' });
  [['Real emails', 'instead of writing them to a log file'], ['Car photos', 'uploaded by the owners themselves'], ['A map', 'to show where each car is picked up'],
   ['A real payment provider', 'thanks to the Proxy, only one class would change'], ['Help when things go wrong', 'a way to settle disputes between owners and renters']].forEach(([h, d], i) => {
    const y = 1.6 + i * 1.0;
    dot(s, i + 1, 0.8, y, 0.6);
    text(s, h, 1.7, y + 0.1, 3.6, 0.45, { fontSize: 19, bold: true, color: C.text2 });
    text(s, d, 5.3, y + 0.12, 7.4, 0.45, { fontSize: 17 });
  });
  s.addNotes('Keep this short. It shows you know the limits of the current version.');

  s = add('Wrap-up'); s.addText('Task summary', { placeholder: 'title' });
  text(s, 'I worked on this project on my own, so every task below is mine.', 0.6, 1.4, 12.1, 0.4, { fontSize: 16, color: C.accent6 });
  const rows = [['Task', 'Who'], ['Requirements, architecture, class and database diagrams', NAME], ['Database schema and demo data', NAME],
    ['Sign-up, login (Singleton) and password recovery (Chain)', NAME], ['Car listings (Builder), search, booking, no double booking', NAME],
    ['Watch list (Observer), messaging and notifications', NAME], ['Payment (Proxy), rental history and reviews', NAME],
    ['Web pages and the Mediator JavaScript', NAME], ['Tests, report, slides and this video', NAME]];
  s.addTable(rows.map((r, i) => r.map(t => ({ text: t, options: i === 0 ? { bold: true, color: C.background1, fill: { color: C.accent1 } } : { color: C.text1, fill: { color: i % 2 ? C.background1 : C.background2 } } }))),
    { x: 0.6, y: 1.95, w: 12.1, colW: [8.6, 3.5], fontSize: 15, rowH: 0.5, border: { type: 'solid', pt: 0.5, color: 'D9D9D9' }, valign: 'middle' });
  s.addNotes('Read the slide title and move on; no need to read every row.');

  s = add('Wrap-up', 'DARK');
  s.addText('Thank you', { placeholder: 'title' });
  s.addText([{ text: 'Everything is on GitHub: github.com/dheyaa-create/Term-Project-Cis-476-001', options: { breakLine: true } },
             { text: 'To run it: pip install -r requirements.txt, then python seed.py, then python run.py', options: { fontSize: 16, color: C.background2 } }], { placeholder: 'body' });
  s.addNotes('Thank the viewer and end the recording.');

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log('done');
})();
