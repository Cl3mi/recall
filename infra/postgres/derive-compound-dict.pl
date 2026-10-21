#!/usr/bin/perl
# Derive a Postgres-consumable compound-splitting dictionary from igerman98.
#
# Why this exists: igerman98 declares COMPOUNDBEGIN/MIDDLE/END in its affix file,
# but grants those flags to words through hunspell *affix flag continuation*
# (e.g. "SFX j 0 0/xoc ." gives class j the flags x, o and c). PostgreSQL's
# spell.c does not implement flag continuation, so it sees zero COMPOUNDBEGIN
# entries and no compound is ever legal - every compound lexizes to NULL.
#
# The fix resolves the intent statically:
#   * any affix class whose rules carry x as a continuation flag -> its words get x
#   * a capitalised entry is a German noun -> may begin, sit inside, or end a
#     compound, so it gets x, y and z
#
# COMPOUNDMIN is set to 4 because that is correct by hunspell semantics, but be
# aware: PostgreSQL PARSES COMPOUNDMIN AND DOES NOT ENFORCE IT. A synthetic
# dictionary splits a 6-character word into 3-character parts even at
# COMPOUNDMIN 20, and on real German text 'Ölfilter' emits the 2-character part
# 'öl'. Do not cite this setting as a safeguard against over-splitting. What
# actually prevents over-splitting is that PostgreSQL prefers a whole-word
# dictionary hit over a decomposition, which is why Motor and Werkstatt survive.
#
# Deliberately permissive: it favours retrieval recall over linguistic precision.
#
# Every guard below exists because the failure it catches would otherwise exit 0
# and ship a silently weaker dictionary. In a build step that is invisible recall
# loss, which is the worst failure shape available - so this dies loudly instead.
use strict;
use warnings;

die "usage: $0 IN.affix IN.dict OUT.affix OUT.dict\n" unless @ARGV == 4;
my ($aff_in, $dict_in, $aff_out, $dict_out) = @ARGV;

# Reading and writing the same path truncates the input mid-read.
die "refusing to write $aff_out in place over its own input\n"  if $aff_out  eq $aff_in;
die "refusing to write $dict_out in place over its own input\n" if $dict_out eq $dict_in;

open my $ain, '<', $aff_in or die "open $aff_in: $!";
my @aff = <$ain>;
close $ain;

# The single-char flag assumption below is load-bearing: appending 'x' to a flag
# string only means "add flag x" when flags are one character each. Under
# FLAG long / FLAG num (both of which PostgreSQL supports) appending corrupts the
# flag list silently - e.g. two-char "xy" would become the malformed "xyz".
for my $line (@aff) {
    die "affix declares a non-single-char FLAG scheme; appending flags would "
      . "corrupt them. Refusing.\n"
        if $line =~ /^FLAG\s/;
}

# Non-UTF-8 input makes the two-byte umlaut match below fail, silently dropping
# every umlaut-initial noun (~575 of them) from compound capability while still
# exiting 0. The Dockerfile only warns about encoding; this is the real gate.
die "affix does not declare SET UTF-8; the umlaut match would silently skip "
  . "Ö/Ä/Ü-initial nouns. Refusing.\n"
    unless grep { /^SET\s+UTF-8/i } @aff;

# Pass 1: which affix classes grant x (COMPOUNDBEGIN) via a continuation field?
my %grants_x;
for my $line (@aff) {
    # SFX <class> <strip> <add>/<continuation-flags> <condition>
    if ($line =~ m{^(?:SFX|PFX)\s+(\S+)\s+\S+\s+\S+/(\S*)} && index($2, 'x') >= 0) {
        $grants_x{$1} = 1;
    }
}
die "no affix class grants COMPOUNDBEGIN - dictionary format changed, refusing\n"
    unless %grants_x;

open my $aout, '>', $aff_out or die "open $aff_out: $!";
for my $line (@aff) {
    $line =~ s/^COMPOUNDMIN\s+.*$/COMPOUNDMIN 4/;
    print {$aout} $line;
}
close $aout;

# Pass 2: mark nouns as compound-capable in all three positions.
# Byte-level match: Ä, Ö, Ü are two bytes in UTF-8 (\xc3\x84, \xc3\x96, \xc3\x9c),
# so a plain [A-Z] test would miss Ölfilter, Übung, Ähre.
my $UPPER = qr/^(?:[A-Z]|\xc3[\x84\x96\x9c])/;

open my $din, '<', $dict_in  or die "open $dict_in: $!";
open my $dout, '>', $dict_out or die "open $dict_out: $!";
my ($noun, $cont, $lineno, $entries, $declared) = (0, 0, 0, 0, undef);
while (my $line = <$din>) {
    $lineno++;
    chomp $line;
    $line =~ s/\r\z//;    # CRLF input would otherwise put \r before the flags
    # Line 1 is igerman98's entry count (75595). Pass it through untouched: this
    # script only rewrites flags, never adds or removes entries, so it stays valid.
    if ($lineno == 1 && $line =~ /^(\d+)$/) {
        $declared = $1;
        print {$dout} "$line\n";
        next;
    }

    my ($word, $flags) = split m{/}, $line, 2;
    $flags = '' unless defined $flags;
    $entries++ if length $line;

    if ($word =~ $UPPER) {
        for my $f (qw(x y z)) { $flags .= $f unless index($flags, $f) >= 0 }
        $noun++;
    } elsif (grep { index($flags, $_) >= 0 } keys %grants_x) {
        unless (index($flags, 'x') >= 0) { $flags .= 'x'; $cont++ }
    }
    print {$dout} length($flags) ? "$word/$flags\n" : "$word\n";
}
close $din;
close $dout;

# A truncated dictionary keeps its stale count line and PostgreSQL never reads it,
# so the only symptom would be quietly fewer words. igerman98's count excludes its
# 14-line licence header, hence the tolerance.
if (defined $declared) {
    my $slack = abs($entries - $declared);
    die "dictionary declares $declared entries but $entries were written "
      . "(difference $slack) - input looks truncated. Refusing.\n"
        if $slack > 32;
}

# Plausibility floors, not just non-zero checks: stripping x from two of the three
# continuation classes still marked *some* entries and exited 0. These thresholds
# sit well below today's real values (25460 nouns, 3 classes) so ordinary upstream
# drift passes, but a structural change fails the build.
die "only $noun nouns marked (expected >20000) - dictionary looks wrong. Refusing.\n"
    unless $noun > 20_000;
die "only " . keys(%grants_x) . " affix class(es) grant COMPOUNDBEGIN (expected >=3) "
  . "- affix format changed. Refusing.\n"
    unless keys(%grants_x) >= 3;

printf STDERR
    "derive-compound-dict: %d noun entries marked x/y/z, %d via continuation classes (%s)\n",
    $noun, $cont, join(',', sort keys %grants_x);
