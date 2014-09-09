__author__ = "Sam Nicholls <sn8@sanger.ac.uk>"
__copyright__ = "Copyright (c) Sam Nicholls"
__version__ = "0.0.2"
__maintainer__ = "Sam Nicholls <sam@samnicholls.net>"

import numpy as np
from math import floor, ceil

from Mountain.IO import fastareaders

class Goldilocks(object):
    """A class for reading Variant Query files and locating regions on a genome
    with particular variant density properties."""
    def load_chromosome(self, arr, data, track):
        return self.strategy.prepare(arr, data, track)

    def __init__(self, strategy, data, is_seq=True, length=1000000, stride=500000, med_window=12.5):
        """Initialise the internal structures and set arguments based on user input."""

        self.strategy = strategy# Search strategy

        self.chr_max_len = {}   # Map chromosomes to the largest variant position
                                # seen across all files

        self.groups = {}        # For each group stores a dict with chromosome
                                # numbers as keys with lists of variant positions
                                # as values

        self.group_buckets = {} # For each group holds keys of region sizes with
                                # values a list of region_i of that size

        self.group_counts = {}  # Holds a list of each region size seen for each
                                # group for calculating quantiles etc.

        self.regions = {}       # Stores information on each region checked

        self.candidates = []    # Lists regions that meet the criteria for final
                                # enrichment and processing

        self.winners = []       # Lists regions that pass the final filter and
                                # enrichment processes

        self.LENGTH = length
        self.STRIDE = stride # NOTE STRIDE must be non-zero, 1 is very a bad idea (TM)
        self.MED_WINDOW = med_window # Middle 25%, can also be overriden later
        self.GRAPHING = False
        self.use_mountain = False

        """Read data"""
        self.groups = data
        if "use_file" in self.groups:
            self.use_mountain = True
            del self.groups["use_file"]

        for group in self.groups:
            #TODO Catch duplicates etc..
            self.group_buckets[group] = {}
            self.group_counts[group] = {}

            if not self.use_mountain:
                for chrom in self.groups[group]:
                    # Remember to exclude 0-index
                    if is_seq:
                        len_current_seq = len(self.groups[group][chrom]) - 1
                    else:
                        len_current_seq = sorted(self.groups[group][chrom])[-1]

                    if chrom not in self.chr_max_len:
                        self.chr_max_len[chrom] = len_current_seq
                    if len_current_seq > self.chr_max_len[chrom]:
                        self.chr_max_len = len_current_seq

        self.group_buckets["total"] = {}
        self.group_counts["total"] = {}

        """Conduct a census of the regions on each chromosome using the user
        defined length and stride. Counting the number of variants present for
        each group."""
        regions = {}
        region_i = 0

        if self.use_mountain:
            #TODO Naughty...
            f = fastareaders.FASTA_Library(self.groups[group][1])
            max_chr_sizes = f.max_chr_sizes.items()
            chro = np.zeros(self.LENGTH+1, np.int8)
            print max_chr_sizes
        else:
            max_chr_sizes = self.chr_max_len.items()

        for chrno, size in sorted(max_chr_sizes):
            chros = {}
            for group in self.groups:
                chros[group] = {}
                for track in self.strategy.TRACKS:
                    if not self.use_mountain:
                        chro = np.zeros(size+1, np.int8)
                        chro.fill(0)
                        chros[group][track] = self.load_chromosome(chro, self.groups[group][chrno], track)

            if self.use_mountain:
                f.seek_fasta(chrno)

            print("[SRCH] Chr:%s" % str(chrno))
            # Ignore 0 position
            for i, region_s in enumerate(range(1, size+1-self.LENGTH+1, self.STRIDE)):
                region_e = region_s + self.LENGTH - 1
                regions[region_i] = {
                    "ichr": i,
                    "group_counts": {"total": {}},
                    "chr": chrno,
                    "pos_start": region_s,
                    "pos_end": region_e
                }
                #print i
                if self.use_mountain:
                    #print "FILL"
                    chro.fill(0)
                    #print "FETCH"
                    seek_last = f.handler.tell()-1
                    sseq = f.fetch_n_bases(self.LENGTH)

                    # Move the file pointer back to read the start of the next window
                    print i
                    f.handler.seek(seek_last, 0)
                    f.fetch_n_bases(self.STRIDE)

                for group in self.groups:
                    for track in self.strategy.TRACKS:
                        if self.use_mountain:
                            #print "FILL"
                            chro.fill(0)
                            chros[group][track] = self.load_chromosome(chro, sseq, track)
                            #print "LOADED"

                            value = self.strategy.evaluate(chros[group][track], track)
                        else:
                            value = self.strategy.evaluate(chros[group][track][region_s:region_e+1], track)

                        if group not in regions[region_i]["group_counts"]:
                            regions[region_i]["group_counts"][group] = {}
                        if track not in regions[region_i]["group_counts"]["total"]:
                            regions[region_i]["group_counts"]["total"][track] = 0

                        regions[region_i]["group_counts"][group][track] = value
                        regions[region_i]["group_counts"]["total"][track] += value

                        # TODO Should we be ignoring these regions if they are empty?
                        if value not in self.group_buckets[group]:
                            # Add this particular number of variants as a bucket
                            self.group_buckets[group][value] = []

                        if value not in self.group_buckets["total"]:
                            self.group_buckets["total"][value] = []

                        # Add the region id to the bucket
                        self.group_buckets[group][value].append(region_i)
                        self.group_buckets["total"][value].append(region_i)

                        # TODO Config option to include 0 in filter metrics
#                   if value > 0:
                        # Append the number of variants counted in this region
                        # for this group to a list used to calculate the median
                        if track not in self.group_counts["total"]:
                            self.group_counts["total"][track] = []
                        if track not in self.group_counts[group]:
                            self.group_counts[group][track] = []

                        self.group_counts[group][track].append(value)
                        self.group_counts["total"][track].append(value)

                        if self.GRAPHING:
                            # NOTE Use i not region_i so regions in the plot start
                            # at 0 for each chromosome rather than cascading
                            print("%s\t%d\t%d\t%d" % (group, chrno, i, value))

                region_i += 1
        self.regions = regions

    def __apply_filter_func(self, func, lower_window, upper_window, group, actual, track):
        valid_funcs = [
                "median",
                "mean",
                "max",
                "min"
        ]

        target = None
        if func.lower() == "median":
            if actual:
                q_low  = np.percentile(np.asarray(self.group_counts[group][track]), 50) - lower_window
                q_high = np.percentile(np.asarray(self.group_counts[group][track]), 50) + upper_window
            else:
                q_low  = np.percentile(np.asarray(self.group_counts[group][track]), 50 - lower_window)
                q_high = np.percentile(np.asarray(self.group_counts[group][track]), 50 + upper_window)
            target = np.percentile(np.asarray(self.group_counts[group][track]), 50)
        if func.lower() == "mean":
            if actual:
                q_low  = np.percentile(np.asarray(self.group_counts[group][track]), 50) - lower_window
                q_high = np.percentile(np.asarray(self.group_counts[group][track]), 50) + upper_window
            else:
                q_low  = np.percentile(np.asarray(self.group_counts[group][track]), 50 - lower_window)
                q_high = np.percentile(np.asarray(self.group_counts[group][track]), 50 + upper_window)
            target = np.percentile(np.asarray(self.group_counts[group][track]), 50)
        elif func.lower() == "max":
            q_high = np.percentile(np.asarray(self.group_counts[group][track]), 100)
            if actual:
                q_low  = np.percentile(np.asarray(self.group_counts[group][track]), 100) - lower_window
            else:
                q_low  = np.percentile(np.asarray(self.group_counts[group][track]), 100 - lower_window)
            target = q_high
        elif func.lower() == "min":
            q_low = np.percentile(np.asarray(self.group_counts[group][track]), 0)
            if actual:
                q_high = np.percentile(np.asarray(self.group_counts[group][track]), 0) + upper_window
            else:
                q_high = np.percentile(np.asarray(self.group_counts[group][track]), 0 + upper_window)
            target = q_low
        else:
            raise NotImplementedException("[FAIL] Function '%s' not supported" % func.lower())
        return q_low, q_high, target


    def __check_exclusions(self, exclusions, region_dict, use_and=False):
        if exclusions is None or len(exclusions) == 0:
            return False

        def exclude_chro(region_dict, chr_bool):
            if chr_bool is True:
                return True
            return False

        def exclude_start(region_dict, operand, position):
            if operand < 0:
                if region_dict["pos_start"] <= position:
                    return True
            elif operand > 0:
                if region_dict["pos_start"] >= position:
                    return True

            return False

        def exclude_end(region_dict, operand, position):
            if operand < 0:
                if region_dict["pos_end"] <= position:
                    return True
            elif operand > 0:
                if region_dict["pos_end"] >= position:
                    return True

            return False

        # Chrom specific exclusions override overall (might be unexpected)
        if region_dict["chr"] in exclusions:
            to_apply = exclusions[region_dict["chr"]]
        elif 0 in exclusions:
            to_apply = exclusions[0]
        else:
            # No exclusions to apply to this region
            return False

        for name in to_apply:
            #TODO Could probably improve with a dict of funcs...
            ret = False
            if name == "chr":
                ret = exclude_chro(region_dict, to_apply["chr"])
            elif name == "start_lte":
                ret = exclude_start(region_dict, -1, to_apply["start_lte"])
            elif name == "start_gte":
                ret = exclude_start(region_dict, 1, to_apply["start_gte"])
            elif name == "end_lte":
                ret = exclude_end(region_dict, -1, to_apply["end_lte"])
            elif name == "end_gte":
                ret = exclude_end(region_dict, 1, to_apply["end_gte"])
            else:
                #TODO Invalid option
                pass

            if use_and:
                # Require all exclusions to be true...
                if ret is False:
                    return False
            else:
                # If we're not waiting on all conditions, we can exclude on the first
                if ret is True:
                    return True

        if use_and:
            # If we didn't bail on a previous false, all conditions must be satisfied
            return True
        return False

    # TODO Pretty hacky at the moment... Just trying some things out!
    def _filter(self, func="median", track="1", actual_distance=None, percentile_distance=None,
            direction=0, group=None, limit=0, exclusions=None, use_and=False):
        distance = None
        actual = False
        if actual_distance is not None and percentile_distance is not None:
            raise Exception("[FAIL] Cannot filter by both actual_distance and percentile_difference. Select one.")

        if actual_distance is not None:
            distance = actual_distance
            actual = True

        if percentile_distance is not None:
            distance = percentile_distance

        if group is None:
            group = "total"

        candidates = []
        if distance is not None:
            upper_window = float(distance) / 2
            lower_window = float(distance) / 2

            if direction > 0:
                upper_window = upper_window * 2
                lower_window = 0.0
            elif direction < 0:
                lower_window = lower_window * 2
                upper_window = 0.0

            q_low, q_high, target = self.__apply_filter_func(func, upper_window, lower_window, group, actual, track)
        else:
            #TODO Pretty ugly.
            q_low, q_high, target = self.__apply_filter_func(func, 0, 0, group, actual, track)
            q_low  = min(np.asarray(self.group_counts[group][track]))
            q_high = max(np.asarray(self.group_counts[group][track]))

        # For each "number of variants" bucket: which map the number of variants
        # seen in a region, to all regions that contained that number of variants
        print("[NOTE] Filtering values between %.2f and %.2f (inclusive)" % (floor(q_low), ceil(q_high)))
        for bucket in self.group_buckets[group]:
            if bucket >= floor(q_low) and bucket <= ceil(q_high):
                # Append all region data structures within the desired range
                # to the list of candidates for enrichment
                candidates += self.group_buckets[group][bucket]

        num_selected = 0
        num_excluded = 0
        num_total = 0

        filtered = []
        for region in sorted(self.regions,
                        key=lambda x: (abs(self.regions[x]["group_counts"][group][track] - target),
                            self.regions[x]["group_counts"][group][track])):
            num_total += 1
            if region in candidates:
                num_selected += 1
                if not self.__check_exclusions(exclusions, self.regions[region], use_and):
                    self.regions[region]["id"] = region
                    filtered.append(self.regions[region])
                else:
                    num_excluded += 1

        # Return the top N elements if desired
        # TODO Report total, selected, selected-excluded and selected-filtered
        if limit:
            filtered = filtered[0:limit]

        print("[NOTE] %d processed, %d match search criteria, %d excluded, %d limit" %
                (num_total, num_selected, num_excluded, limit))

        return filtered

    def _sort(self):
        pass
