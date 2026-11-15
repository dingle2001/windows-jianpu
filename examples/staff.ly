\version "2.24.4"
\header { title = "Windows Etude" subtitle = "Single staff test score" tagline = ##f }
\paper { #(set-paper-size "a4") ragged-last = ##f }
\score {
  \new Staff \fixed c' {
    \set Staff.instrumentName = "Flute"
    \key g \major
    \time 4/4
    \tempo 4 = 84
    g4 a b d' |
    c'4 b a2 |
    b8 c' d' b a4 g |
    fis4 g r2 \break |
    g4. a8 b4 c' |
    d'4 e' d' b |
    a8 b c' a g4 fis |
    g1 \bar "|."
  }
  \layout { }
}
