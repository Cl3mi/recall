"""Common German and Austrian first names, for the free-text token sweep.

The entity sweep knows company suffixes and surname shapes but not first names, and the first
real run released one as a title token. A name here withholds the word wherever it appears, so
the list leaves out every name that is also an ordinary or technical word. Considered and left
out for that reason: 'max', 'mark', 'nick', 'wolf', 'rosa', 'otto' (Ottomotor), 'frank',
'ernst', 'eva' (the material), 'jan' (January), 'kai', 'iris', 'linde' (the forklift maker),
'wolfram' (tungsten), 'heide', 'finn', 'till', 'pascal' (the unit), 'malte' (a verb form),
'marina', 'jasmin', 'liane', 'manuel' (a typo of 'manuell'), 'flo', 'leo', 'kim'. Missing a
rare name costs little: a token must still clear the floor.

Only spellings the tokenizer can produce are listed: it keeps A-Z, a-z and the German umlauts
and drops every other letter. Umlaut names therefore appear three ways ('jürgen', 'juergen',
'jurgen'), and an accented name only in its plain form ('andre', 'rene'): 'andré' tokenises to
'andr', and listing such a fragment would withhold whatever other word it is.
"""

from __future__ import annotations

import re

# The tokenizer keeps hyphens, so 'hans-peter' is one token; slashes and dots join names too.
_PARTS = re.compile(r"[\s\-/.]+")

_MALE = """
achim adrian alexander alfred alois andre andreas anton armin arne arnold arthur axel
benedikt benjamin benno bernd bernhard björn bjoern bjorn bodo boris bruno burkhard carsten
christian christoph christopher claus clemens constantin cornelius daniel david dennis detlef
dieter dietmar dietrich dirk dominik eberhard eckhard edgar edmund egon elias emil engelbert
erhard erich erik erwin eugen fabian falk felix ferdinand florian franz friedhelm friedrich
fritz gabriel gebhard georg gerald gerd gerhard gernot gottfried gregor guido gunnar gunter
günter guenter günther guenther gunther gustav hannes harald hartmut heiko heinrich heinz helmut
helmuth henning henrik herbert hermann herwig holger horst hubert ingo jakob jannik jens
joachim jochen johann johannes jonas jörg joerg jorg josef julian jürgen juergen jurgen justus
kaspar
karl karsten klaus konrad konstantin kurt lars leonhard leopold lorenz lothar ludwig lukas
lutz maik manfred marcel marco marcus mario markus martin matthias mathias meinhard
michael mirko moritz niklas nikolaus nils norbert olaf oliver oskar patrick paul peter
philipp rainer ralf ralph reinhard reinhold rene richard robert roland rolf rudolf rüdiger
ruediger rudiger rupert sascha sebastian siegfried sigmund simon steffen stefan stephan sven thilo
thomas thorsten timo tobias torsten udo ulf ulrich uwe valentin veit viktor vinzenz volker
waldemar walther werner wilfried wilhelm willi wolfgang
"""

_FEMALE = """
adelheid agnes alexandra alina amelie andrea angela angelika anita anja anke anna annette
antje antonia astrid barbara beate bettina bianca birgit brigitte britta carina carola
carolin caroline charlotte christa christel christiane christina christine claudia cornelia
dagmar daniela diana doris dorothea edeltraud edith elfriede elisabeth elke ella elsa emilia
emma erika esther franziska frauke friederike gabriele gerda gertrud gisela greta gudrun
hannah hannelore hedwig heidrun heike helene helga henriette hildegard ilona ilse imke ingeborg
ingrid irene irmgard isabel isabella jacqueline jana janina jennifer jessica johanna
josefine judith julia juliane jutta karin karoline katharina kathrin katja katrin kerstin
klara clara kristina larissa laura lea lena leonie lieselotte lisa luise magdalena
maike manuela mareike maren margarete margit maria marianne marie marion marlene
martina mathilde melanie michaela miriam monika nadine nadja natalie nicole nina petra
regina renate ricarda rita ronja ruth sabine sabrina sandra sarah silke silvia simone sonja
sophia sophie stefanie stephanie susanne svenja swantje tamara tanja theresa therese ulrike
ursula ute valentina vanessa verena veronika viktoria waltraud wiebke yvonne
"""

# Short and familiar forms that a ticket uses as often as the full name.
_SHORT = """
alex andi basti ben chris conny gabi hans hansi jessi kevin michi mike moni sepp steffi susi
tim toni tom uli
"""

# More first names found in German, Austrian and Swiss workplaces: dialect and short forms, and
# the common Turkish, Balkan, Polish, Italian and Spanish names. Names that are also ordinary or
# technical words stay out (see the docstring), and so does anything shorter than four letters
# unless it is a familiar short form.
_MALE_MORE = """
aaron abdullah adem adnan ahmet akin albert albrecht aleksander alessandro alexandre alfonso
ali amin anatol anselm ansgar antonio arno arndt artur aurel baris bastian bartosz bela bengt
berthold bertram birger bogdan bonifaz borislav branko burak cedric christof cihan claudio
curt cem cengiz dario darko denis dejan dimitri dogan dragan dusan edin eduard ekkehard elmar
emanuel emre enrico ercan erdal erdogan ernesto eren fabio fatih felipe filip florin
francesco frederik fredrik gerrit giovanni giuseppe goran hakan hamza hanno hartwig hasan heiner
helge hendrik henri hilmar hinrich hugo ibrahim igor ilias ilja ismail ivan jacob jaroslav
jascha jasper jaroslaw jochim jonathan jordan josip jozef juan kadir kemal kenan klemens knut
korbinian kristian krzysztof kuno lambert lazar lennart lorenzo lucas luigi luka lukasz mahmut
malik marat marian mariusz marko marvin mateusz matej mathis matthaeus maurice mauro melih mert
metin michal mihai miroslav mirsad murat mustafa nico nicolas niels nikola nikolai olli omar
orhan osman otmar pawel pedro philip piet pirmin rafael raimund ramon raphael rasmus reiner
reinald remo renato ricardo rico rinaldo robin rocco rodolfo ronald rouven ruben rufus
salvatore samuel sandro sead selim semih serdar sergej sergio severin silvio slobodan stanislaw
stefano tarek tayfun thiemo thorben tilman tillmann timm tobi tomas tomasz torben tristan ufuk
umut urs vladimir wenzel wieland wojciech wolfhard yannick yasin younes yusuf zoran zeljko
angelo anton antonius bartholomaeus beat bernward bruno bryan cornel damian darius demir dennis
dian domenic donato dorian egbert elias erol evren ferdi fikret fridolin gaetano georgios
gianni gordan guenni gundolf hajo hannes hardy harry hasso helmar hennes herrmann hilger holm
hussein ilker imre ingmar ivo jaan jannis jarno jeremias jerome jobst joshua juergen jurij
karim kasimir kay kilian kjell konni kosta kristof ladislav lasse laszlo levent lian lucian
ludger magnus maksim marek marius martino masud matteo maxim mehdi menno mikael milan mirco
mischa mladen nadir nazim nedim nenad nikos norman oguz olivier orlando oskar ottokar pantelis
patric pawel peer petar petro phil pierre radek radoslaw ragnar ralf rami raul reno rexhep
rikard rocky rudolph samir sandor sasa saul sedat sinan sixtus sokol sven tamas teodor theo
theodor thies tiago timon tino tolga tom toni uwe valerio vasil vitali vito viktor wally
wiktor willibald yakup yavuz yunus zdenek zlatko
mehmet marc luca noah maximilian ewald alfons roman piotr
"""

_FEMALE_MORE = """
adriana aileen aleksandra alena alessia alice alma amalia ana anastasia andra angelina anika
anina anisa annabelle annalena annemarie annika antonella arzu asli ayse aylin bahar beatrice
belinda benita bernadette bianka carmen cathrin cecilia celina charlene christl cindy clarissa
claire constanze corinna cosima dana daria deborah denise desiree dilara dilek dina donata dora
doreen dorit ebru edda elena eleonore elif elina elisa elvira emely emine emira enya erna
ernestine eveline evelyn fabienne fatma felicitas fiona flora florentine franka frieda gaby
gina giulia gloria gordana gretel gunda hanna hatice hedi heidemarie helen hella hilde hilke
ida inga ines isolde ivana ivonne jamila janet janine jasmina jelena jenny joanna jolanda
jovana jule julika kaja karina karla kassandra katarina kathleen katia klaudia kristin laila
lale lara larisa laurena leila lejla lidia lina linda lioba lotte lucia lucie ludmila luna
lydia magda maja malin mandy marcella margot margret mariana marielle marika marissa marta
mathilda mechthild meike melissa merle mia michelle milena mira mirjam mona nadia nele nelli
nesrin nevin nicola nikola nora olga ottilie patricia paula pauline peggy philine pia pinar
rahel rebecca rebekka regine reni resi riccarda roberta romy rosemarie rosi roswitha saskia
selma semra serap sevim sibylle sidonie sigrun sina sinem sofia solveig sonia stella suna
sylvia sybille tabea tatjana tessa thea tina tuba ulla uta vera viola vivien walburga wanda
wilma yasemin yvette zeynep zofia zora zuzana
agata alexa alisa amina angie anneliese annegret annelie antonie apollonia ariane asya
aurelia ayla ayten behiye berit betty bine bozena brunhilde cansu cathleen celine charline
chiara christiana dajana dalia damla danuta debora delia derya dijana dominika drita edina
elea elfi elia eliane emelie esra fatime felizitas gabi gesine gisa giselle halina hanife
ingeburg irina isabelle jadwiga jasmine jessika jolina josephine kamila karolina kasia
katharine kiara korina krista kristiane laureen leah lilli lilian lilly liliana lorena
lucy lutgard madeleine magdalene marga margareta margarita marit marlies marta mayra melek
melina merve mina mirela monique nancy naomi natascha neslihan nilgun noemi nuray olivia
paulina radmila rosalie rozalia ruzica sanja sara selin senta sevgi simona sladjana
stanislawa svetlana sylwia tamina tereza tijana ursel valeska vesna vlasta wenke yildiz zehra
zuzanna sigrid
"""

# Regional and workplace short forms, and the umlaut and plain spellings the tokenizer can make
# of the common Turkish names.
_REGIONAL = """
hias lois xaver rudi luis franzl much kurti sepp hansl lenz seppl bertl ferdl poldi resl vroni
hueseyin huseyin hüseyin ozlem oezlem özlem oemer ömer omer sueleyman süleyman suleyman
guenes günes gunes cueneyt cüneyt cuneyt goekhan gökhan gokhan oezgur özgür ozgur
"""

FIRST_NAMES = frozenset(
    _MALE.split()
    + _FEMALE.split()
    + _SHORT.split()
    + _MALE_MORE.split()
    + _FEMALE_MORE.split()
    + _REGIONAL.split()
)

# Common surnames: German, Austrian, Swiss, Turkish, Polish, Balkan and Italian. Written in both
# the umlaut and the ae/oe/ue spelling because the tokenizer keeps the umlaut and a ticket types
# either; `SURNAMES` also adds the ae/oe/ue/ss spelling of every umlaut entry, so a form can never
# be present without its twin. A surname that is also an everyday or technical word is left out
# on purpose, because listing it would erase that word from the report: considered and rejected
# are klein, lang, lange, schwarz, braun, winter, sommer, stein, jung, kern, horn, hahn, kraft,
# brand, reiter, hammer, meister, schlosser, kurz, gross, weiss, frei, berg, bach, fuchs, vogel,
# busch and sauer.
_SURNAMES = """
mueller müller schmidt schneider fischer weber meyer meier maier mayer mayr wagner becker schulz
hoffmann hofmann schaefer schäfer koch bauer richter schroeder schröder neumann zimmermann
krueger krüger hartmann schmitt werner schmitz krause lehmann schmid schulze koehler köhler
herrmann koenig könig walter huber kaiser peters scholz moeller möller schubert friedrich keller
guenther günther frank berger winkler roth beck lorenz baumann franke albrecht schuster simon
ludwig boehm böhm kraus martin schumacher kraemer krämer vogt jaeger jäger otto seidel heinrich
brandt haas schreiber graf schulte dietrich ziegler kuhn kühn kuehn pohl engel bergmann thomas
voigt arnold wolff pfeiffer sander peter ernst bergner mohr bender kiefer neubauer lutz seifert
heine wendt conrad fritz held hess heß hein ritter hoppe lindemann pfeifer ullrich witt
wittmann zander aigner auer baumgartner brunner binder ebner egger eder eibl fink fleischmann
fuerst fürst gasser gruber haider hauser hechenberger hofer holzer kofler koller lechner lehner
leitner mair margreiter moser pichler reisinger schwaiger steiner steinberger wallner
wechselberger wimmer wieser zangerl pfeifer strobl tschurtschenthaler walch weiler
yilmaz kaya demir sahin şahin celik çelik yildiz yildirim oezdemir özdemir aydin arslan dogan
doğan kilic kılıç aslan cetin çetin kara koc koç kurt oezkan özkan simsek şimşek polat
nowak kowalski wisniewski wojcik kowalczyk kaminski lewandowski zielinski szymanski wozniak
dabrowski kozlowski jankowski mazur kwiatkowski krawczyk piotrowski grabowski nowakowski
pawlowski michalski zajac krol wieczorek jablonski wroblewski majewski olszewski stepien
horvat novak kovac kovacs babic maric petrovic jovanovic nikolic markovic djordjevic ilic
stojanovic pavlovic savic popovic knezevic vukovic jankovic radovic milic todorovic
rossi russo ferrari esposito bianchi romano colombo ricci marino greco bruno gallo conti
mancini costa giordano rizzo lombardi moretti barbieri fontana santoro mariani rinaldi
caruso ferrara galli martini leone longo gentile martinelli vitale lombardo serra coppola
garcia martinez lopez gonzalez rodriguez fernandez sanchez perez gomez
abel ackermann adam ahrens albers althaus altmann ambros ammann anders andres appel arndt
assmann bachmann backhaus bader baier balzer barth bartsch bauch bauernfeind baur bayer
beckmann behrens beier bell benz berends bergmann bernhard beyer bien bischoff bittner blank
blum bock bode boettcher böttcher bohn bohnert bolz born borner bosch brand braune bremer
brinkmann brockmann bruckner brueckner brückner bruns buchholz buchner burger burkhardt busse
christ clasen claus cramer daube decker degen dehn deppe diehl dierks dietz dittrich doll
dorn dreher drescher dressler duerr dürr eberhardt eckert ehlers eichhorn eisele elsner
emmerich endres engelhardt erdmann ertl esser everding fabian faber fahrenholz falk fassbender
faust feldmann fiedler fink fleck forster foerster förster franz freitag freund frey fricke
fries fromm funk gabriel gebhardt gehrke geiger geisler gerber gerlach gerstner giese glaser
glatz goetz götz goldmann gottschalk graef gräf grimm gross grosse grote gruenewald grünewald
grund guenzel günzel gundlach haag haase hagedorn hagen hahne halbeisen hammerschmidt hampel
hanke hansen hanssen harms hartung hasse hauck haupt hecht heck heilmann heimann heinz heinze
helm hempel henke hennig henschel hermann herold herzog hesse heuer hildebrandt hinz hirsch
hoefer höfer hoeffner höffner hoffmeister hofmeister holl holler holst holtz hopf horn hornung
hubert hummel hutter immel ingenhoff jacob jacobs jahn jakob janssen jansen jordan jost jung
junker kaestner kästner kahl kaiser kalb kamp kampf kappel karl kastner kaufmann kellner kern
kessler keil kirchner kirsch klaus klee klemm klingler knapp knauer knoll kobler koehn köhn
kolb kopp kraft krebs kremer kroll kruse kuehne kühne kunz kunze kuppers lammers landgraf
lampe lamprecht lauer laufer lauterbach lenz lessing lehnert lieb liebig linde
loeffler löffler lohmann lohse luetke lütke maas mahler mann marx matthes mauer maurer mehl
meinhardt meiser merkel mertens messner metzger michel moeckel möckel mohn morgenstern
muehlbauer mühlbauer muench münch naumann nickel niemann nitsche nolte noll oberle
oehler öhler opitz ott pabst pape paulsen peschel petersen pfaff pfister philipp pietsch plank
platz pohlmann poppe probst prinz puetz pütz quast rademacher rapp rauch rausch rehm reichel
reimann reinhard reinhardt reuter rieger riedel riedl rieger rinke rittmann roeder röder roese
rose rothe rudolph ruf rupp sachs sahm salzmann sattler schaaf schade schaller scharf schauer
schenk scherer schick schiller schindler schlegel schlund schmalz schmeling schmied schnabel
schnell schoen schön scholl schorn schott schramm schreck schreyer schuh schuett schütt schulte
schultz schulze schwab schwan schwarzer schweizer seeger seitz sieber siebert siegel sievers
simmer singer sinn sperling spiess spieß stadler stahl stark staudt stegmann steffen stehle
 steinbach steinmetz stephan stoll stolz storch strack strauss strauß strehle
stucke stuermer stürmer suess süß teichmann teufel thiele thiel tietz timm trapp trautmann
trost uhlig ulbrich ulmer unger urban vetter vieth vogler voss voß wacker wagener wahl wald
waldmann walz wanner weidner weigel weih weinert weise weisser wendel wenzel wiegand wiese
wild wilhelm wilke winkelmann wirth wittig woelk wölk wohlfahrt wolter wulf
zabel zahn zeller zeuner zick ziegler zilch zimmer zink zoellner zöllner zorn
"""

# A twin-less umlaut entry is repaired here: every umlaut spelling gets its ae/oe/ue/ss form.
_TRANSLITERATE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_ALLOWED = set("abcdefghijklmnopqrstuvwxyzäöüß")

# The surnames that are also words. Subtracted rather than merely not typed above, so that a
# later edit to the list cannot bring one back unnoticed (a test pins each of them as absent).
_WORD_COLLISIONS = frozenset(
    {
        *("klein", "lang", "lange", "schwarz", "braun", "winter", "sommer", "stein", "jung"),
        *("kern", "horn", "hahn", "kraft", "brand", "reiter", "hammer", "meister", "schlosser"),
        *("kurz", "gross", "grosse", "weiss", "frei", "berg", "bach", "fuchs", "vogel", "busch"),
        *("sauer",),
    }
)

_RAW = {s for s in _SURNAMES.split() if set(s) <= _ALLOWED} - _WORD_COLLISIONS
SURNAMES = frozenset(_RAW | {s.translate(_TRANSLITERATE) for s in _RAW})


def contains_first_name(value: str) -> bool:
    """True when any part of `value` (a token, bigram or trigram, split on whitespace, hyphens,
    slashes and dots) is a first name."""
    return any(part.casefold() in FIRST_NAMES for part in _PARTS.split(value) if part)


def contains_surname(value: str) -> bool:
    """True when any part of `value` is a listed surname, with the same splitting."""
    return any(part.casefold() in SURNAMES for part in _PARTS.split(value) if part)
