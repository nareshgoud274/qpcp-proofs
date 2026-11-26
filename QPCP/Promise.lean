import QPCP.Defs
import QPCP.Qudit

/-!
# QPCP: the intended promise problem (docs/spec/promise.tex, sections 1-4 and 7)

STATUS: DRAFT. Maintainer-written. Not yet reviewed by a specialist in
Hamiltonian complexity. It builds on `QPCP.Defs` and `QPCP.Qudit` and changes
neither. Nothing here is a step in `steps.json`.

Each declaration carries, in a one-line comment above it, the sentence of
`docs/spec/promise.tex` it formalizes ("§n: ...").

Conventions this file fixes, which the page does not settle:

* A bit is `Fin 2`, with `0` for false and `1` for true; basis order is
  `0` then `1`.
* The `r`-th local coordinate of a term (`r : Fin j`) is the `r`-th listed
  site, `sites.get r`.
* Rounding and approximation (§5) are not modelled.
-/

namespace QPCP.Promise

open Matrix QPCP

/-! ## Exact dyadic numbers (§2) -/

-- §2: "real and imaginary parts that are dyadic rationals, each given exactly as (p,e) ∈ ℤ × ℕ meaning p/2^e"
/-- A dyadic rational `num / 2 ^ exp`, given exactly by its numerator and exponent. -/
structure Dyadic where
  /-- The integer numerator `p`. -/
  num : ℤ
  /-- The exponent `e` of the denominator `2 ^ e`. -/
  exp : ℕ
  deriving DecidableEq

-- §2: "(p,e) ∈ ℤ × ℕ meaning p/2^e"
/-- The value `p / 2 ^ e` of a dyadic, as a rational. -/
def Dyadic.toRat (d : Dyadic) : ℚ := d.num / 2 ^ d.exp

-- §2: "entries have real and imaginary parts that are dyadic rationals"
/-- A complex number whose real and imaginary parts are exact dyadics. -/
structure DyadicComplex where
  /-- The real part. -/
  re : Dyadic
  /-- The imaginary part. -/
  im : Dyadic
  deriving DecidableEq

-- §2: "(p,e) ... meaning p/2^e", for each of the real and imaginary parts
/-- The value of a dyadic complex number in `ℂ`. -/
noncomputable def DyadicComplex.toComplex (z : DyadicComplex) : ℂ :=
  ⟨(z.re.toRat : ℝ), (z.im.toRat : ℝ)⟩

-- helper (§2 entries): the dyadic complex number 0, used by the §7 violation matrix
/-- The dyadic complex number `0 = 0/2^0 + i·0/2^0`. -/
def DyadicComplex.zero : DyadicComplex := ⟨⟨0, 0⟩, ⟨0, 0⟩⟩

-- helper (§2 entries): the dyadic complex number 1, used by the §7 violation matrix
/-- The dyadic complex number `1 = 1/2^0 + i·0/2^0`. -/
def DyadicComplex.one : DyadicComplex := ⟨⟨1, 0⟩, ⟨0, 0⟩⟩

/-! ## Encoded terms (§2) -/

-- §2: "Each encoded term t is a pair (S,h)": S distinct sites, 0≤j≤k; h a q^j×q^j matrix indexed by {0,…,q−1}^j
/-- An encoded term `(S, h)`: an ordered list of `j ≤ k` distinct sites (possibly
empty) and a matrix of exact dyadic entries indexed by local configurations of
those sites, the `r`-th local coordinate belonging to the `r`-th listed site. -/
structure EncodedTerm (q n k : ℕ) where
  /-- The ordered tuple of sites `(i_1, …, i_j)`. -/
  sites : List (Fin n)
  /-- The sites are distinct. -/
  nodup : sites.Nodup
  /-- `j ≤ k`. -/
  length_le : sites.length ≤ k
  /-- The local matrix `h`, indexed by `{0,…,q-1}^j`. -/
  entries : Matrix (Fin sites.length → Fin q) (Fin sites.length → Fin q) DyadicComplex

/-! ## Encoded length and polynomial size bounds (§2, "Size")

The lengths below are counts of symbols in an abstract encoding, defined
recursively here; they are not the length of any bit string. A family's two
polynomials (`Family.pm`, `Family.pt`, both evaluated at `n + 1`) bound exactly:

* `pm`: the number of terms `m`, `I.terms.length`;
* `pt`: each term's `EncodedTerm.length`, that is its `sites.length + 1`, plus
  `i + 1` for each listed site `i`, plus `DyadicComplex.length` of every one of
  its `q^j · q^j` entries (`intLength` of each numerator, `e + 1` for each
  exponent).

`RawInstance.length` (`n + 1` plus the sum of the terms' lengths) is defined
but not bounded directly. No claim is made about running time on bit strings
until a self-delimiting serialization of raw inputs is specified and shown
polynomially equivalent to these lengths; that serialization is not built here.
-/

-- §2 Size: "p is written in signed binary"
/-- Length of an integer in signed binary: one sign symbol and its binary digits. -/
def intLength (p : ℤ) : ℕ := 1 + Nat.size p.natAbs

-- §2 Size: "p is written in signed binary and e in unary"
/-- Length of a dyadic `(p, e)`: `p` in signed binary, `e` in unary (`e + 1` symbols). -/
def Dyadic.length (d : Dyadic) : ℕ := intLength d.num + (d.exp + 1)

-- §2 Size: the length of an entry is the length of its two dyadic parts
/-- Length of a dyadic complex number. -/
def DyadicComplex.length (z : DyadicComplex) : ℕ := z.re.length + z.im.length

-- §2 Size: "running time is measured in the total encoded length"
/-- Length of an encoded term: its number of sites and each site in unary, then
every entry of its matrix. -/
def EncodedTerm.length {q n k : ℕ} (t : EncodedTerm q n k) : ℕ :=
  (t.sites.length + 1) + (t.sites.map fun i => (i : ℕ) + 1).sum +
    ∑ x, ∑ y, (t.entries x y).length

/-! ## Validity (§2, "Validity") -/

-- §2: "entries have real and imaginary parts that are dyadic rationals" (their values in ℂ)
/-- The local matrix `h` with its entries' values in `ℂ`. -/
noncomputable def EncodedTerm.localMatrix {q n k : ℕ} (t : EncodedTerm q n k) :
    Matrix (Fin t.sites.length → Fin q) (Fin t.sites.length → Fin q) ℂ :=
  t.entries.map DyadicComplex.toComplex

open scoped ComplexOrder in
-- §2 Validity: "A raw input is valid if every h is Hermitian with 0 ⪯ h ⪯ I."
/-- A valid encoded term: `h` is Hermitian, positive semidefinite, and at most the identity. -/
def EncodedTerm.Valid {q n k : ℕ} (t : EncodedTerm q n k) : Prop :=
  t.localMatrix.IsHermitian ∧ t.localMatrix.PosSemidef ∧ (1 - t.localMatrix).PosSemidef

-- §2 Validity: "in exact rational arithmetic" (the real parts of h)
/-- The real parts of the entries of `h`, as rationals. -/
def EncodedTerm.reRat {q n k : ℕ} (t : EncodedTerm q n k) :
    Matrix (Fin t.sites.length → Fin q) (Fin t.sites.length → Fin q) ℚ :=
  fun x y => (t.entries x y).re.toRat

-- §2 Validity: "in exact rational arithmetic" (the imaginary parts of h)
/-- The imaginary parts of the entries of `h`, as rationals. -/
def EncodedTerm.imRat {q n k : ℕ} (t : EncodedTerm q n k) :
    Matrix (Fin t.sites.length → Fin q) (Fin t.sites.length → Fin q) ℚ :=
  fun x y => (t.entries x y).im.toRat

-- helper (§2 Validity): the exact test of positive semidefiniteness used by ValidRat
/-- Every principal minor of a rational matrix is nonnegative. -/
def PrincipalMinorsNonneg {ι : Type} [Fintype ι] [DecidableEq ι] (M : Matrix ι ι ℚ) : Prop :=
  ∀ s : Finset ι, 0 ≤ (M.submatrix (fun i : s => (i : ι)) (fun i : s => (i : ι))).det

-- §2 Validity: "validity is decidable in exact rational arithmetic"
/-- An exact rational test for validity. Writing `h = A + iB` with `A`, `B`
rational: `h` is Hermitian (`A` symmetric, `B` antisymmetric), and the real
symmetric matrices `[[A, -B], [B, A]]` (for `h`) and `[[I - A, B], [-B, I - A]]`
(for `I - h`) have every principal minor nonnegative. It is a finite conjunction
of comparisons of rationals, so it is decidable. -/
def EncodedTerm.ValidRat {q n k : ℕ} (t : EncodedTerm q n k) : Prop :=
  t.reRatᵀ = t.reRat ∧ t.imRatᵀ = -t.imRat ∧
  PrincipalMinorsNonneg (Matrix.fromBlocks t.reRat (-t.imRat) t.imRat t.reRat) ∧
  PrincipalMinorsNonneg (Matrix.fromBlocks (1 - t.reRat) t.imRat (-t.imRat) (1 - t.reRat))

-- §2 Validity: "validity is decidable in exact rational arithmetic" (ValidRat is decidable)
instance {q n k : ℕ} (t : EncodedTerm q n k) : Decidable t.ValidRat := by
  unfold EncodedTerm.ValidRat PrincipalMinorsNonneg; infer_instance

/-! ## Denotation (§3) -/

-- §2: "S=(i_1,…,i_j) is an ordered tuple of distinct sites" (S as a set)
/-- The support of an encoded term: its listed sites, as a set. -/
def EncodedTerm.support {q n k : ℕ} (t : EncodedTerm q n k) : Finset (Fin n) :=
  t.sites.toFinset

-- §3: "the r-th tensor factor of h acts on site i_r"
/-- The local configuration `(x_{i_1}, …, x_{i_j})` that a term reads from a global one. -/
def EncodedTerm.localConfig {q n k : ℕ} (t : EncodedTerm q n k) (x : QConfig q n) :
    Fin t.sites.length → Fin q :=
  fun r => x (t.sites.get r)

open Classical in
-- §3: "⟨x|H_(S,h)|y⟩ = h[(x_{i_1},…,x_{i_j}),(y_{i_1},…,y_{i_j})] if x_i = y_i for all i ∉ S, 0 otherwise"
/-- The operator an encoded term denotes, entry by entry as in §3. -/
noncomputable def EncodedTerm.op {q n k : ℕ} (t : EncodedTerm q n k) : QOp q n :=
  Matrix.of fun x y =>
    if QAgreeOff t.support x y then t.localMatrix (t.localConfig x) (t.localConfig y) else 0

/-! ### The decoded operator is `h ⊗ I`, reindexed -/

section Reindex

variable {q n k : ℕ} (t : EncodedTerm q n k)

-- helper (§3): position r ↔ the r-th listed site i_r
/-- The listed sites, as members of the list, indexed by position. -/
abbrev siteEquiv : Fin t.sites.length ≃ {i // i ∈ t.sites} := List.Nodup.getEquiv t.sites t.nodup

-- helper (§3): a global configuration is (its values on S, its values off S)
open Classical in
/-- A global configuration is its local configuration on the listed sites
together with its values off the support. -/
noncomputable def splitEquiv :
    QConfig q n ≃ (Fin t.sites.length → Fin q) × ({i // i ∉ t.support} → Fin q) where
  toFun x := (t.localConfig x, fun i => x i.1)
  invFun p i :=
    if h : i ∈ t.sites then p.1 ((siteEquiv t).symm ⟨i, h⟩)
    else p.2 ⟨i, by simpa [EncodedTerm.support] using h⟩
  left_inv x := by
    funext i
    by_cases h : i ∈ t.sites
    · have := (siteEquiv t).apply_symm_apply ⟨i, h⟩
      simp only [dite_eq_left h, EncodedTerm.localConfig]
      exact congrArg x (congrArg Subtype.val this)
    · simp [dite_eq_right h]
  right_inv p := by
    obtain ⟨u, w⟩ := p
    refine Prod.ext ?_ ?_
    · funext r
      have hr : t.sites.get r ∈ t.sites := List.get_mem _ _
      simp only [EncodedTerm.localConfig, dite_eq_left hr]
      have : (siteEquiv t).symm ⟨t.sites.get r, hr⟩ = r :=
        (siteEquiv t).symm_apply_eq.mpr rfl
      rw [this]
    · funext i
      have : i.1 ∉ t.sites := by simpa [EncodedTerm.support] using i.2
      simp [dite_eq_right this]

-- helper (§3): "x_i = y_i for all i ∉ S" is equality of the off-S parts
lemma agreeOff_iff (x y : QConfig q n) :
    QAgreeOff t.support x y ↔ (splitEquiv t x).2 = (splitEquiv t y).2 := by
  constructor
  · intro h; funext i; exact h i.1 i.2
  · intro h i hi; exact congrFun h ⟨i, hi⟩

-- §3: "the r-th tensor factor of h acts on site i_r and the identity acts elsewhere" (h ⊗ I, reindexed)
open scoped Kronecker in
lemma op_eq_kronecker :
    t.op = (t.localMatrix ⊗ₖ (1 : Matrix ({i // i ∉ t.support} → Fin q)
      ({i // i ∉ t.support} → Fin q) ℂ)).submatrix (splitEquiv t) (splitEquiv t) := by
  ext x y
  simp only [EncodedTerm.op, Matrix.of_apply, Matrix.submatrix_apply, Matrix.kroneckerMap_apply,
    Matrix.one_apply]
  by_cases h : QAgreeOff t.support x y
  · rw [ite_eq_left h, ite_eq_left ((agreeOff_iff t x y).mp h), mul_one]; rfl
  · rw [ite_eq_right h, ite_eq_right (fun h' => h ((agreeOff_iff t x y).mpr h')), mul_zero]

end Reindex

-- §3: "the r-th tensor factor of h acts on site i_r and the identity acts elsewhere" (QActsOn)
/-- The decoded operator acts only on the listed sites. -/
def DecodeActsOn : Prop :=
  ∀ (q n k : ℕ) (t : EncodedTerm q n k), QActsOn t.support t.op

-- §3: the denotation acts only on S (proved; the decoder needs it)
/-- Proved here because the decoder below must supply it to build a `NormalizedTerm`. -/
theorem decodeActsOn : DecodeActsOn := by
  intro q n k t
  refine ⟨fun u v => t.localMatrix (fun r => u ⟨t.sites.get r, by simp [EncodedTerm.support]⟩)
    (fun r => v ⟨t.sites.get r, by simp [EncodedTerm.support]⟩),
    fun x y => ⟨fun h => ?_, fun h => ?_⟩⟩
  · simp only [EncodedTerm.op, Matrix.of_apply, ite_eq_left h]; rfl
  · simp only [EncodedTerm.op, Matrix.of_apply, ite_eq_right h]

-- §3: "0 ⪯ H" for one valid term (needed by the decoder)
open scoped ComplexOrder Kronecker in
lemma op_posSemidef {q n k : ℕ} (t : EncodedTerm q n k) (hv : t.Valid) : t.op.PosSemidef := by
  rw [op_eq_kronecker, posSemidef_submatrix_equiv]
  exact hv.2.1.kronecker Matrix.PosSemidef.one

-- §3: "H ⪯ I" for one valid term (needed by the decoder)
open scoped ComplexOrder Kronecker in
lemma one_sub_op_posSemidef {q n k : ℕ} (t : EncodedTerm q n k) (hv : t.Valid) :
    (1 - t.op).PosSemidef := by
  have h1 : (1 : QOp q n) = ((1 : Matrix (Fin t.sites.length → Fin q) _ ℂ) ⊗ₖ
      (1 : Matrix ({i // i ∉ t.support} → Fin q) ({i // i ∉ t.support} → Fin q) ℂ)).submatrix
        (splitEquiv t) (splitEquiv t) := by
    rw [Matrix.one_kronecker_one, Matrix.submatrix_one_equiv]
  have h2 : 1 - t.op = Matrix.submatrix
      (((1 : Matrix (Fin t.sites.length → Fin q) _ ℂ) - t.localMatrix) ⊗ₖ
        (1 : Matrix ({i // i ∉ t.support} → Fin q) ({i // i ∉ t.support} → Fin q) ℂ))
      (splitEquiv t) (splitEquiv t) := by
    rw [op_eq_kronecker]
    ext x y
    simp only [Matrix.sub_apply, Matrix.submatrix_apply, Matrix.kroneckerMap_apply, sub_mul]
    congr 1
    by_cases hxy : x = y
    · subst hxy; simp
    · have hne : splitEquiv t x ≠ splitEquiv t y := (splitEquiv t).injective.ne hxy
      rw [Matrix.one_apply_ne hxy]
      by_cases h1' : (splitEquiv t x).1 = (splitEquiv t y).1
      · rw [Matrix.one_apply_ne (fun h2' => hne (Prod.ext h1' h2')), mul_zero]
      · rw [Matrix.one_apply_ne h1', zero_mul]
  rw [h2, posSemidef_submatrix_equiv]
  exact hv.2.2.kronecker Matrix.PosSemidef.one

-- §3: "Each valid encoding has exactly one denotation"; the term (S,h) denotes H_(S,h)
/-- The decoder: a valid encoded term denotes a normalized term on its listed sites. -/
noncomputable def decode {q n k : ℕ} (t : EncodedTerm q n k) (hv : t.Valid) :
    NormalizedTerm q n k where
  support := t.support
  card_le := by rw [EncodedTerm.support, List.toFinset_card_of_nodup t.nodup]; exact t.length_le
  op := t.op
  posSemidef := op_posSemidef t hv
  le_one := one_sub_op_posSemidef t hv
  actsOn := decodeActsOn q n k t

/-! ## Parameters, instances, and the promise (§1, §2, §4) -/

-- §1: "integers q≥2 (local dimension) and k≥1 (locality), and rational thresholds 0≤a<b≤1"
/-- The fixed parameters of a problem family. -/
structure Params where
  /-- Local dimension. -/
  q : ℕ
  /-- Locality. -/
  k : ℕ
  /-- The yes threshold. -/
  a : ℚ
  /-- The no threshold. -/
  b : ℚ
  two_le_q : 2 ≤ q
  one_le_k : 1 ≤ k
  zero_le_a : 0 ≤ a
  a_lt_b : a < b
  b_le_one : b ≤ 1

-- §2: "An instance consists of an integer n≥0 (number of sites) and a list of encoded terms"
/-- A raw input: a number of sites and a list of encoded terms (repetitions count). -/
structure RawInstance (q k : ℕ) where
  /-- The number of sites `n`. -/
  n : ℕ
  /-- The encoded terms `t_1, …, t_m`, in order, with repetitions. -/
  terms : List (EncodedTerm q n k)

-- §2 Size: "The number of sites n is also written in unary"
/-- Length of a raw input: `n` in unary (`n + 1`), then each term's `EncodedTerm.length`.
An abstract symbol count, not a bit-string length (see the section note above). -/
def RawInstance.length {q k : ℕ} (I : RawInstance q k) : ℕ :=
  (I.n + 1) + (I.terms.map EncodedTerm.length).sum

-- §2 Size: "A problem family fixes polynomials bounding m and each term's encoded length in n+1."
/-- The number of terms and each term's length are bounded by `pm` and `pt` at `n + 1`. -/
def RawInstance.SizeBounded {q k : ℕ} (pm pt : Polynomial ℕ) (I : RawInstance q k) : Prop :=
  I.terms.length ≤ pm.eval (I.n + 1) ∧ ∀ t ∈ I.terms, t.length ≤ pt.eval (I.n + 1)

-- §2: "a list of m≥1 encoded terms"; Validity: "valid if every h is Hermitian with 0⪯h⪯I"
/-- A raw input is valid: it has at least one term, and every term is valid. -/
def RawInstance.Valid {q k : ℕ} (I : RawInstance q k) : Prop :=
  I.terms ≠ [] ∧ ∀ t ∈ I.terms, t.Valid

-- §3: "The instance denotes H = Σ_{t=1}^m H_t"
/-- The Hamiltonian of a valid raw input: its terms decoded, in order, repetitions kept. -/
noncomputable def RawInstance.hamiltonian {q k : ℕ} (I : RawInstance q k) (hv : I.Valid) :
    NormalizedHamiltonian q I.n k :=
  ⟨I.terms.attach.map fun t => decode t.1 (hv.2 t.1 t.2)⟩

-- §1 and §2 Size: "A problem family fixes q, k, a, b" and "fixes polynomials bounding m and each term's encoded length in n+1"
/-- A problem family: its parameters and the two size polynomials. -/
structure Family where
  /-- `q`, `k`, `a`, `b`. -/
  params : Params
  /-- Bounds the number of terms `m`, at `n + 1`. -/
  pm : Polynomial ℕ
  /-- Bounds each term's `EncodedTerm.length`, at `n + 1`. -/
  pt : Polynomial ℕ

-- §4: "For a valid instance:"; §2: invalid inputs, and inputs outside the family's size bounds, are in neither Yes nor No
/-- A raw input is an instance of the family: it is valid and within the family's size bounds. -/
def Family.IsInstance (F : Family) (I : RawInstance F.params.q F.params.k) : Prop :=
  I.Valid ∧ I.SizeBounded F.pm F.pt

-- §4: the promise problem is defined on the family's instances only
/-- An instance of a family's promise problem. -/
def FamilyInstance (F : Family) : Type :=
  {I : RawInstance F.params.q F.params.k // F.IsInstance I}

-- §3: "The instance denotes H = Σ_{t=1}^m H_t"
/-- The Hamiltonian of a family instance. -/
noncomputable def FamilyInstance.hamiltonian {F : Family} (I : FamilyInstance F) :
    NormalizedHamiltonian F.params.q I.1.n F.params.k :=
  I.1.hamiltonian I.2.1

-- §4: "Yes if λ_min(H) ≤ a·m"
/-- A yes-instance of the family: ground energy at most `a · m`. -/
def Yes (F : Family) (I : FamilyInstance F) : Prop :=
  RelYes I.hamiltonian (F.params.a : ℝ)

-- §4: "No if λ_min(H) ≥ b·m"
/-- A no-instance of the family: ground energy at least `b · m`. -/
def No (F : Family) (I : FamilyInstance F) : Prop :=
  RelNo I.hamiltonian (F.params.b : ℝ)

/-! ## Statements about the promise problem (closed propositions) -/

-- §2 Validity: "validity is decidable in exact rational arithmetic"
/-- Validity is equivalent to the exact rational test `ValidRat`, which is decidable. -/
def ValidDecidable : Prop :=
  ∀ (q n k : ℕ) (t : EncodedTerm q n k), t.Valid ↔ t.ValidRat

-- §4: "Because a<b and m≥1, no instance is both."
/-- No instance of any family is both a yes- and a no-instance. -/
def YesNoDisjoint : Prop :=
  ∀ (F : Family) (I : FamilyInstance F), ¬ (Yes F I ∧ No F I)

/-! ## The classical milestone (§7, `q = 2`) -/

-- §7: "A Boolean constraint is a pair (S,P) with S as above and P:{0,1}^j→{true,false}."
/-- A Boolean constraint: an ordered list of distinct sites and a predicate on
their local assignments (bit `0` is false, `1` is true). -/
structure BoolConstraint (n k : ℕ) where
  /-- The ordered tuple of sites. -/
  sites : List (Fin n)
  /-- The sites are distinct. -/
  nodup : sites.Nodup
  /-- `j ≤ k`. -/
  length_le : sites.length ≤ k
  /-- The predicate `P`; the constraint is satisfied where it is true. -/
  pred : (Fin sites.length → Fin 2) → Bool

-- §7: "the local 2^j×2^j violation matrix is built from the truth table of P"
/-- The local violation matrix: `1` on the diagonal where `P` is false, `0` elsewhere. -/
def BoolConstraint.violationEntries {n k : ℕ} (c : BoolConstraint n k) :
    Matrix (Fin c.sites.length → Fin 2) (Fin c.sites.length → Fin 2) DyadicComplex :=
  fun u v => if u = v ∧ c.pred u = false then DyadicComplex.one else DyadicComplex.zero

-- §7: the violation matrix is "passed through the same decoder as §3" (as an encoded term)
/-- A Boolean constraint as an encoded term. -/
abbrev BoolConstraint.toEncoded {n k : ℕ} (c : BoolConstraint n k) : EncodedTerm 2 n k :=
  ⟨c.sites, c.nodup, c.length_le, c.violationEntries⟩

-- helper (§7): the local violation matrix's value in ℂ, a diagonal of 0s and 1s
/-- The diagonal violation indicator on local assignments, in `ℂ`. -/
noncomputable def BoolConstraint.violationDiag {n k : ℕ} (c : BoolConstraint n k) :
    Matrix (Fin c.toEncoded.sites.length → Fin 2) (Fin c.toEncoded.sites.length → Fin 2) ℂ :=
  Matrix.diagonal fun u => if c.pred u = false then (1 : ℂ) else 0

-- helper (§7): the decoded local violation matrix is the 0/1 diagonal
lemma BoolConstraint.localMatrix_eq {n k : ℕ} (c : BoolConstraint n k) :
    c.toEncoded.localMatrix = c.violationDiag := by
  ext u v
  show DyadicComplex.toComplex (c.violationEntries u v) = _
  simp only [BoolConstraint.violationEntries, BoolConstraint.violationDiag, Matrix.diagonal_apply]
  split_ifs with h1 h2 h2 <;>
    simp_all [DyadicComplex.toComplex, DyadicComplex.one, DyadicComplex.zero, Dyadic.toRat,
      Complex.ext_iff]

-- §2 Validity applied to §7: the violation matrix is Hermitian with 0 ⪯ h ⪯ I
open scoped ComplexOrder in
lemma BoolConstraint.toEncoded_valid {n k : ℕ} (c : BoolConstraint n k) : c.toEncoded.Valid := by
  have hd : (1 : Matrix (Fin c.toEncoded.sites.length → Fin 2) _ ℂ) - c.violationDiag =
      Matrix.diagonal fun u => if c.pred u = false then (0 : ℂ) else 1 := by
    ext u v
    simp only [BoolConstraint.violationDiag, Matrix.sub_apply, Matrix.one_apply,
      Matrix.diagonal_apply]
    split_ifs <;> simp_all
  refine ⟨?_, ?_, ?_⟩
  · rw [c.localMatrix_eq, BoolConstraint.violationDiag]
    exact Matrix.isHermitian_diagonal_of_self_adjoint _ (funext fun u => by
      simp only [Pi.star_apply]; split_ifs <;> simp)
  · rw [c.localMatrix_eq, BoolConstraint.violationDiag, Matrix.posSemidef_diagonal_iff]
    intro u; split_ifs <;> simp
  · rw [c.localMatrix_eq, hd, Matrix.posSemidef_diagonal_iff]
    intro u; split_ifs <;> simp

-- §7: "Its term is the diagonal projector onto violating assignments", built through the decoder
/-- The term of a Boolean constraint: its violation matrix, decoded by `decode`. -/
noncomputable def BoolConstraint.term {n k : ℕ} (c : BoolConstraint n k) : NormalizedTerm 2 n k :=
  decode c.toEncoded c.toEncoded_valid

-- §7: "P(x_{i_1},…,x_{i_j})" (the local assignment a constraint reads)
/-- The local assignment `(x_{i_1}, …, x_{i_j})` a constraint reads. -/
def BoolConstraint.localConfig {n k : ℕ} (c : BoolConstraint n k) (x : QConfig 2 n) :
    Fin c.sites.length → Fin 2 :=
  fun r => x (c.sites.get r)

-- §7: "For a list of m≥1 constraints, … Σ_t Π_t"
/-- The Hamiltonian of a list of constraints: their terms, in order. -/
noncomputable def boolHamiltonian {n k : ℕ} (cs : List (BoolConstraint n k)) :
    NormalizedHamiltonian 2 n k :=
  ⟨cs.map BoolConstraint.term⟩

-- §7: "#{t : x violates t}" (x violates t when P(x_{i_1},…,x_{i_j}) = false)
/-- The number of constraints in the list (with repetitions) that `x` violates. -/
def violationCount {n k : ℕ} (cs : List (BoolConstraint n k)) (x : QConfig 2 n) : ℕ :=
  cs.countP fun c => !c.pred (c.localConfig x)

-- §7: "Π_(S,P) = Σ_{x : P(x_{i_1},…,x_{i_j}) = false} |x⟩⟨x|" (the decoded term, full matrix equality)
/-- The decoded Boolean term is the diagonal matrix of the violation indicator. -/
def BoolTermDiagonal : Prop :=
  ∀ (n k : ℕ) (c : BoolConstraint n k),
    c.term.op = Matrix.diagonal fun x => if c.pred (c.localConfig x) = false then (1 : ℂ) else 0

-- §7: "the proof shows its diagonal entry at a global assignment is the violation indicator, and sums these"
/-- The sum of a constraint list's terms is the diagonal matrix of the violation count. -/
def BoolSumDiagonal : Prop :=
  ∀ (n k : ℕ) (cs : List (BoolConstraint n k)),
    (boolHamiltonian cs).toOp = Matrix.diagonal fun x => (violationCount cs x : ℂ)

-- §7: "λ_min(Σ_t Π_t)/m = min_{x∈{0,1}^n} #{t : x violates t}/m"
/-- Ground energy over `m` is the minimum fraction of violated constraints. -/
def BoolGroundEnergy : Prop :=
  ∀ (n k : ℕ) (cs : List (BoolConstraint n k)), cs ≠ [] →
    groundEnergyOn (boolHamiltonian cs).toOp / cs.length =
      ⨅ x : QConfig 2 n, (violationCount cs x : ℝ) / cs.length

/-! ## Proofs: statement 4, and the two tests of §7 -/

-- §7: "the proof shows its diagonal entry at a global assignment is the violation indicator"
theorem boolTermDiagonal : BoolTermDiagonal := by
  intro n k c
  ext x y
  simp only [BoolConstraint.term, decode, EncodedTerm.op, Matrix.of_apply, c.localMatrix_eq,
    BoolConstraint.violationDiag, Matrix.diagonal_apply]
  have hloc : ∀ z, c.toEncoded.localConfig z = c.localConfig z := fun _ => rfl
  by_cases hxy : x = y
  · subst hxy
    have : QAgreeOff c.toEncoded.support x x := fun _ _ => rfl
    simp_all
  · rw [ite_eq_right hxy]
    by_cases hoff : QAgreeOff c.toEncoded.support x y
    · rw [ite_eq_left hoff]
      have hl : c.toEncoded.localConfig x ≠ c.toEncoded.localConfig y := by
        intro hl
        apply hxy
        funext i
        by_cases hi : i ∈ c.toEncoded.support
        · have hi' : i ∈ c.sites := by simpa [EncodedTerm.support, BoolConstraint.toEncoded] using hi
          obtain ⟨r, rfl⟩ := List.mem_iff_get.mp hi'
          exact congrFun hl r
        · exact hoff i hi
      rw [ite_eq_right hl]
    · rw [ite_eq_right hoff]

-- §7: "… and sums these"
theorem boolSumDiagonal : BoolSumDiagonal := by
  intro n k cs
  induction cs with
  | nil =>
    ext x y
    simp [boolHamiltonian, NormalizedHamiltonian.toOp, violationCount]
  | cons c cs ih =>
    have hc := boolTermDiagonal n k c
    simp only [boolHamiltonian, NormalizedHamiltonian.toOp, List.map_cons, List.sum_cons] at ih ⊢
    rw [ih, hc, Matrix.diagonal_add]
    congr 1; funext x
    simp only [violationCount, List.countP_cons]
    cases c.pred (c.localConfig x) <;> simp [add_comm]

/-! ### Test A: `n = 1`, constraints `(x = true), (x = true), (x = false)` -/

-- §7 Test A: the constraint (x = b) on the one site
/-- The constraint `x_0 = b` on one site. -/
def bitIs (b : Fin 2) : BoolConstraint 1 1 :=
  ⟨[0], List.nodup_singleton 0, le_refl _, fun u => decide (u ⟨0, by simp⟩ = b)⟩

-- §7 Test A: "n=1 with the list (x=1),(x=1),(x=0)"
/-- Test A's constraint list, with the repetition. -/
def testA : List (BoolConstraint 1 1) := [bitIs 1, bitIs 1, bitIs 0]

-- §7 Test A: "must give H = diag(2,1) in basis order (0,1)"
theorem testA_hamiltonian :
    (boolHamiltonian testA).toOp = Matrix.diagonal fun x : QConfig 2 1 => ![(2 : ℂ), 1] (x 0) := by
  rw [boolSumDiagonal]
  congr 1; funext x
  have hx : x = fun _ => x 0 := funext fun i => by fin_cases i; rfl
  rw [hx]
  generalize x 0 = v
  rcases (show v = 0 ∨ v = 1 by omega) with rfl | rfl
  · rw [show violationCount testA (fun _ => 0) = 2 by decide]; simp
  · rw [show violationCount testA (fun _ => 1) = 1 by decide]; simp

-- §7 Test A: "It also catches deduplication" (m = 3)
/-- Test A has three terms: the repetition is kept. -/
theorem testA_numTerms : (boolHamiltonian testA).numTerms = 3 := rfl

-- §7 Test A: "and value exactly 1/3"
/-- Test A's ground energy over `m = 3` is `1/3`, given the proposition of step `S027` (the
ground energy of a classical cost operator is its minimum), written out here so that this
module does not import `QPCP.Statements`; the record proves it as `QPCP.Proof.S027`. -/
theorem testA_value (h27 : ∀ (n : ℕ) (f : Config n → ℝ), groundEnergy (costOp f) = ⨅ x, f x) :
    groundEnergyOn (boolHamiltonian testA).toOp / (boolHamiltonian testA).numTerms = 1 / 3 := by
  rw [testA_hamiltonian, testA_numTerms]
  have hcost : (Matrix.diagonal fun x : QConfig 2 1 => ![(2 : ℂ), 1] (x 0)) =
      costOp (fun x : Config 1 => ![(2 : ℝ), 1] (x 0)) := by
    unfold costOp; congr 1; funext x
    rcases (show x 0 = 0 ∨ x 0 = 1 by omega) with h | h <;> simp [h]
  have hge : groundEnergyOn (costOp (fun x : Config 1 => ![(2 : ℝ), 1] (x 0))) =
      groundEnergy (costOp (fun x : Config 1 => ![(2 : ℝ), 1] (x 0))) := rfl
  have hmin : (⨅ x : Config 1, ![(2 : ℝ), 1] (x 0)) = 1 := by
    apply le_antisymm
    · exact (ciInf_le (Set.finite_range _).bddBelow (fun _ => 1)).trans_eq (by simp)
    · exact le_ciInf fun x => by
        rcases (show x 0 = 0 ∨ x 0 = 1 by omega) with h | h <;> simp [h]
  rw [hcost, hge, h27, hmin]
  norm_num

/-! ### Test B: `n = 2`, support `(1, 0)`, local projector onto the string `10` -/

-- §7 Test B: "n=2, support tuple (1,0), local projector onto the string 10"
/-- Violated exactly at the local string `10`: local coordinate `0` (site 1) is `1`
and local coordinate `1` (site 0) is `0`. Its violation matrix is the projector onto `10`. -/
def testB : BoolConstraint 2 2 :=
  ⟨[1, 0], by decide, le_refl _, fun u => !decide (u = ![1, 0])⟩

-- §7 Test B: "the term must select exactly the global assignment x_0=0, x_1=1"
theorem testB_term :
    testB.term.op = Matrix.of fun x y : QConfig 2 2 =>
      if x = ![0, 1] ∧ y = ![0, 1] then (1 : ℂ) else 0 := by
  rw [boolTermDiagonal]
  ext x y
  simp only [Matrix.diagonal_apply, Matrix.of_apply]
  have key : (testB.pred (testB.localConfig x) = false) ↔ x = ![0, 1] := by
    simp only [testB, Bool.not_eq_false', decide_eq_true_eq]
    constructor
    · intro h; funext i; fin_cases i
      · have := congrFun h 1; simpa [BoolConstraint.localConfig] using this
      · have := congrFun h 0; simpa [BoolConstraint.localConfig] using this
    · intro h; subst h; funext r; fin_cases r <;> rfl
  by_cases hxy : x = y
  · subst hxy; simp [key]
  · rw [ite_eq_right hxy]
    split_ifs with h
    · exact absurd (h.1.trans h.2.symm) hxy
    · rfl

/-! ### The size bounds reach Yes and No (reviewer's counterexample) -/

-- helper (§2, §4): the zero term on the empty support, q = 2, k = 1 (its 1×1 matrix is [0])
/-- The zero term on no sites. -/
def zeroTerm : EncodedTerm 2 0 1 :=
  ⟨[], List.nodup_nil, Nat.zero_le _, fun _ _ => DyadicComplex.zero⟩

-- helper (§2, §4): n = 0 with two zero terms on the empty support
/-- The reviewer's input: `n = 0` and the list `zeroTerm, zeroTerm`. -/
def twoZeroTerms : RawInstance 2 1 := ⟨0, [zeroTerm, zeroTerm]⟩

-- helper (§1, §2): q = 2, k = 1, a = 0, b = 1, a term-count bound of the constant 1, and any pt
/-- A family whose term-count polynomial is the constant `1`. -/
noncomputable def oneTermFamily (pt : Polynomial ℕ) : Family :=
  ⟨⟨2, 1, 0, 1, le_refl _, le_refl _, le_refl _, zero_lt_one, le_refl _⟩, Polynomial.C 1, pt⟩

open scoped ComplexOrder in
-- §2 Validity: the reviewer's input passes the physical validity check
theorem twoZeroTerms_valid : twoZeroTerms.Valid := by
  have h0 : zeroTerm.localMatrix = 0 := by
    ext u v
    show DyadicComplex.toComplex (zeroTerm.entries u v) = 0
    simp [zeroTerm, DyadicComplex.toComplex, DyadicComplex.zero, Dyadic.toRat, Complex.ext_iff]
  have hv : zeroTerm.Valid := by
    refine ⟨?_, ?_, ?_⟩
    · rw [h0]; exact Matrix.isHermitian_zero
    · rw [h0]; exact Matrix.PosSemidef.zero
    · rw [h0, sub_zero]; exact Matrix.PosSemidef.one
  refine ⟨by simp [twoZeroTerms], fun t ht => ?_⟩
  have : t = zeroTerm := by
    rcases List.mem_cons.mp ht with h | h
    · exact h
    · rcases List.mem_cons.mp h with h | h
      · exact h
      · exact absurd h List.not_mem_nil
  exact this ▸ hv

-- §2 Size: "A problem family fixes polynomials bounding m"; the reviewer's input is not a family instance
theorem twoZeroTerms_not_instance (pt : Polynomial ℕ) :
    ¬ (oneTermFamily pt).IsInstance twoZeroTerms := by
  rintro ⟨-, hm, -⟩
  simp [twoZeroTerms, oneTermFamily] at hm

end QPCP.Promise
