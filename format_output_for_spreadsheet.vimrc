" always only work on lines starting with date

" remove trailing ')'
:g/^202/s,)$,,

" separate host from issuer
:g/^202/s, (,\t,

" re-issued means Y
:g/^202/s:  re-issued, :Y\t:

" not issued means N
:g/^202/s: not issued, :N\t:

" get rid of sugar
:g/^202/s, expiration:,\t,

" Capitalize as desired
:g/^202/s,unreachable,Unreachable,
:g/^202/s,not deployed,Not Deployed,

" Final tab swap
:g/^202/s,: ,\t,
