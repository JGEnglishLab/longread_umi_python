from abc import ABC, abstractmethod
import re
from Bio import SeqIO
from Bio.Align import PairwiseAligner
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from collections import defaultdict, Counter
from statistics import mean, median
import numpy as np

class ConsensusStrategy(ABC):

    def __init__(self):
        self.binPattern = re.compile('seq_bin(\d+)\.fq')

    @abstractmethod
    def generate_consensus_sequences(self, binPaths: list): pass

class ReferenceConsensusGenerator:

    def adjust_all_string_lengths(strs, buffer_length):
        max_length = len(max(strs, key = len))
        strs = [x.ljust(max_length+buffer_length) for x in strs]
        return strs

    def initialize_consensus_output_string(strs, excerpt_length):
        tempList = [x[:excerpt_length] for x in strs]
        final = max(set(tempList), key = tempList.count)
        return final

    def find_next_character(subStrings, tempPattern):
        pattern = re.compile(tempPattern + '.')
        baseCountDict = defaultdict(list)
        all_characters = []
        for x in subStrings:
            r = pattern.search(x)
            if r: baseCountDict[r.group(0)[-1]].append(r.start(0)); all_characters.append(r.group(0)[-1])
        c = Counter(all_characters)
        percent_benchmark = .2
        benchmark = int(len(subStrings)*percent_benchmark)
        common = c.most_common()
        if len(common) > 1 and common[1][1] > benchmark:
            min_val = min([median(baseCountDict[x[0]]) for x in common[:2]])
            res = [x[0] for x in common[:2] if median(baseCountDict[x[0]]) == min_val]
            return res[0]
        return c.most_common()[0][0]

    @classmethod
    def find_initial_consensus(self, strs, excerpt_length = 10, buffer_length = 20):
        strs = self.adjust_all_string_lengths(strs, buffer_length)
        final = self.initialize_consensus_output_string(strs, excerpt_length)
        for i in range(len(strs[0])-buffer_length):
            subStrings = [x[i:i+buffer_length] for x in strs]
            tempPattern = final[-excerpt_length:]
            nex = self.find_next_character(subStrings, tempPattern)
            final += nex
        return final.strip(' ')


class PairwiseStrategy(ConsensusStrategy):

    def __init__(self):
        super().__init__()

    def find_aligned_differences(self, seq1, seq2):
        aligner = PairwiseAligner()
        alignments = aligner.align(seq1,seq2)
        indices = alignments[0].aligned
        a_idx, b_idx = list(indices[0]), list(indices[1])
        a_idx.insert(0, (0,0))
        b_idx.insert(0, (0,0))
        a_idx.append((len(seq1),len(seq1)))
        b_idx.append((len(seq2),len(seq2)))

        diffs = []

        for i in range(len(a_idx)-1):
            start = a_idx[i][1]
            end = a_idx[i+1][0]
            insert = seq2[b_idx[i][1]:b_idx[i+1][0]]
            if start == end and len(insert)==0: continue
            diffs.append((start, end, insert))
        return diffs

    def update_candidate_seq_by_common_diffs(self, candidateSeq, binRecords):
        diffs = []
        for binRecord in binRecords:
            tempDiffs = self.find_aligned_differences(candidateSeq, str(binRecord.seq))
            tempDiffs = [(x[0], x[1], x[2], binRecord.id) for x in tempDiffs]
            diffs.extend(tempDiffs)
        finalSeq = candidateSeq[:]

        tempDiffs = [(x[0],x[1],x[2]) for x in diffs]
        most_common_diff = Counter(tempDiffs).most_common(1)[0][0]
        #print(most_common_diff)
        start, end, insert = most_common_diff
        finalSeq = finalSeq[:start] + insert + finalSeq[end:]
        return finalSeq, diffs


    def find_average_aligned_score(self, candidateSeq, binRecords):
        binSeqs = [str(record.seq) for record in binRecords]
        aligner = PairwiseAligner()
        aligner.mismatch_score = -1
        aligner.open_gap_score = -1
        aligner.extend_gap_score = -0.5
        scores = []
        score_to_ids = []
        for i in range(len(binSeqs)):
            #if i % 100 == 0: print(i)
            alignments = aligner.align(candidateSeq, binSeqs[i])
            scores.append(alignments[0].score)
            score_to_ids.append([binRecords[i].id, alignments[0].score])
        return mean(scores), score_to_ids

    def generate_pairwise_consensus_sequence_from_file(self, binPath):
        binRecords = [record for record in SeqIO.parse(binPath, "fastq")]
        diffs = []
        binSeqs = [str(record.seq) for record in binRecords]
        refSeq = ReferenceConsensusGenerator.find_initial_consensus(binSeqs)
        bestScore = -np.inf
        candidateSeq = refSeq[:]
        counter = 0
        curScore, score_to_ids = self.find_average_aligned_score(candidateSeq, binRecords)
        while curScore >= bestScore:
            bestScore = curScore
            tempSeq, diffs = self.update_candidate_seq_by_common_diffs(candidateSeq, binRecords)
            curScore, score_to_ids = self.find_average_aligned_score(tempSeq, binRecords)
            if curScore >= bestScore: candidateSeq = tempSeq
            counter += 1
            if counter > 15: return candidateSeq
        return candidateSeq


    def generate_consensus_sequences(self, binPaths: list) -> list:
        outputDir = '/'.join(binPaths[0].split('/')[:-2]) + '/'
        records = []
        allDiffs = []
        for i in range(len(binPaths)):
            binPath = binPaths[i]
            binNum = self.binPattern.search(binPath).group(1)
            consensusSeq = self.generate_pairwise_consensus_sequence_from_file(binPath)
            seqRecord = SeqRecord(Seq(consensusSeq),id=binNum)
            records.append(seqRecord)
            if i % 1 == 0: print(f'{i+1} / {len(binPaths)}', flush=True)
        return records
