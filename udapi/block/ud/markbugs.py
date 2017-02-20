"""Block MarkBugs for checking suspicious/wrong constructions in UD v2.

See http://universaldependencies.org/release_checklist.html#syntax
and http://universaldependencies.org/svalidation.html
IMPORTANT: the svalidation.html overview is not generated by this code,
but by SETS-search-interface rules, which may give different results than this code.

Usage:
udapy -s ud.MarkBugs < in.conllu > marked.conllu 2> log.txt

Errors are both logged to stderr and marked within the nodes' MISC field,
e.g. `node.misc['Bug'] = 'aux-chain'`, so the output conllu file can be
searched for "Bug=" occurences.

Author: Martin Popel
based on descriptions at http://universaldependencies.org/svalidation.html
"""
import collections
import logging
import re

from udapi.core.block import Block

REQUIRED_FEATURE_FOR_UPOS = {
    'PRON': 'PronType',
    'DET': 'PronType',
    'NUM': 'NumType',
    'VERB': 'VerbForm',
}

class MarkBugs(Block):
    """Block for checking suspicious/wrong constructions in UD v2."""

    def __init__(self, save_stats=True, skip=None, **kwargs):
        """Create the MarkBugs block object.

        Args:
        save_stats: store the bug statistics overview into `document.misc["bugs"]`?
        skip: a regex. If `re.search(skip, short_msg)` the node is not reported.
            You can use e.g. `skip=no-(VerbForm|NumType|PronType)`.
            Default = None (or empty string) which means no skipping.
        """
        super().__init__(**kwargs)
        self.save_stats = save_stats
        self.stats = collections.Counter()
        self.skip_re = re.compile(skip) if (skip is not None and skip != '') else None

    def log(self, node, short_msg, long_msg):
        """Log node.address() + long_msg and add ToDo=short_msg to node.misc."""
        if self.skip_re is not None and self.skip_re.search(short_msg):
            return
        logging.debug('node %s %s: %s', node.address(), short_msg, long_msg)
        if node.misc['Bug']:
            if short_msg not in node.misc['Bug']:
                node.misc['Bug'] += ',' + short_msg
        else:
            node.misc['Bug'] = short_msg
        self.stats[short_msg] += 1

    # pylint: disable=too-many-branches
    def process_node(self, node):
        form, deprel, upos, feats = node.form, node.deprel, node.upos, node.feats
        parent = node.parent

        for dep in ('aux', 'fixed', 'appos', 'goeswith'):
            if deprel == dep and parent.deprel == dep:
                self.log(node, dep + '-chain', dep + ' dependencies should not form a chain.')

        for dep in ('flat', 'fixed', 'conj', 'appos', 'goeswith'):
            if deprel == dep and node.precedes(parent):
                self.log(node, dep + '-rightheaded',
                         dep + ' relations should be left-headed, not right.')

        if deprel == 'cop' and upos not in ('AUX', 'PRON'):
            self.log(node, 'cop-upos', 'deprel=cop upos!=AUX|PRON (but %s)' % upos)

        if deprel == 'mark' and upos == 'PRON':
            self.log(node, 'mark-upos', 'deprel=mark upos=PRON')

        if deprel == 'det' and upos not in ('DET', 'PRON'):
            self.log(node, 'det-upos', 'deprel=det upos!=DET|PRON (but %s)' % upos)

        if deprel == 'punct' and upos != 'PUNCT':
            self.log(node, 'punct-upos', 'deprel=punct upos!=PUNCT (but %s)' % upos)

        for i_upos, i_feat in REQUIRED_FEATURE_FOR_UPOS.items():
            if upos == i_upos and not node.feats[i_feat]:
                self.log(node, 'no-' + i_feat, 'upos=%s but %s feature is missing' % (upos, i_feat))

        if feats['VerbForm'] == 'Fin':
            if upos not in ('VERB', 'AUX'):
                self.log(node, 'finverb-upos', 'VerbForm=Fin upos!=VERB|AUX (but %s)' % upos)
            if not feats['Mood']:
                self.log(node, 'finverb-mood', 'VerbForm=Fin but Mood feature is missing')

        if feats['Degree'] and upos not in ('ADJ', 'ADV'):
            self.log(node, 'degree-upos',
                     'Degree=%s upos!=ADJ|ADV (but %s)' % (feats['Degree'], upos))

        subject_children = [n for n in node.children if 'subj' in n.deprel]
        if len(subject_children) > 1:
            self.log(node, 'multi-subj', 'More than one [nc]subj(:pass)? child')

        object_children = [n for n in node.children if n.deprel in ('obj', 'ccomp')]
        if len(object_children) > 1:
            self.log(node, 'multi-obj', 'More than one obj|ccomp child')

        # In addition to http://universaldependencies.org/svalidation.html
        if parent.deprel == 'punct':
            self.log(node, 'punct-child', 'parent.deprel=punct')

        # See http://universaldependencies.org/u/overview/syntax.html#the-status-of-function-words
        # TODO: Promotion by Head Elision: It is difficult to detect this exception.
        #       So far, I have just excluded "det" from the forbidded parent.deprel set
        #       because it is quite often the promoted head and the false-alarm probability is high.
        #       In future, we could check the enhanced dependencies for empty nodes.
        # TODO: Function word modifiers: so far I have included advmod to the allowed deprel set.
        #       This catches the cases like "not every", "exactly two" and "just when".
        #       It seems the documentation does not allow any other deprel than advmod,
        #       so there should be no false alarms. Some errors are not reported, i.e. the cases
        #       when advmod incorrectly depends on a function word ("right before midnight").
        if parent.deprel in ('aux', 'cop', 'mark', 'clf', 'case'):
            if deprel not in ('conj', 'cc', 'punct', 'fixed', 'goeswith', 'advmod'):
                self.log(node, parent.deprel + '-child',
                         'parent.deprel=%s deprel!=conj|cc|punct|fixed|goeswith' % parent.deprel)

        # goeswith should be left-headed, but this is already checked, so let's skip right-headed.
        if deprel == 'goeswith' and parent.precedes(node):
            span = node.root.descendants(add_self=1)[parent.ord:node.ord]
            intruder = next((n for n in span[1:] if n.deprel != "goeswith"), None)
            if intruder is not None:
                self.log(intruder, 'goeswith-gap', "deprel!=goeswith but lies within goeswith span")
            else:
                for goeswith_node in span:
                    if goeswith_node.misc['SpaceAfter'] == 'No':
                        self.log(goeswith_node, 'goeswith-space', "deprel=goeswith SpaceAfter=No")

        if upos == 'SYM' and form.isalpha():
            self.log(node, 'sym-alpha', "upos=SYM but all form chars are alphabetical: " + form)

        if upos == 'PUNCT' and  any(char.isalpha() for char in form):
            self.log(node, 'punct-alpha', "upos=PUNCT but form has alphabetical char(s): " + form)

    def after_process_document(self, document):
        total = 0
        message = 'ud.MarkBugs Error Overview:'
        for bug, count in sorted(self.stats.items(), key=lambda pair: (pair[1], pair[0])):
            total += count
            message += '\n%20s %10d' % (bug, count)
        message += '\n%20s %10d\n' % ('TOTAL', total)
        logging.warning(message)
        if self.save_stats:
            document.meta["bugs"] = message
        self.stats.clear()
