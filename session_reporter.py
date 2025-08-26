import os
import datetime
import json

class SessionReporter:
    def __init__(self, input_csv_path):
        self.input_csv_path = input_csv_path
        self.putt_data = []
        self.total_putts = 0
        self.putt_counter = 0
        self.total_makes = 0
        self.total_misses = 0
        self.makes_by_category = {}
        self.misses_by_category = {"CATCH": 0, "RETURN": 0, "TIMEOUT": 0}
        self.max_consecutive_makes = 0
        self.consecutive_makes_counts = {3: 0, 5: 0, 7: 0, 10: 0, 15: 0, 21: 0, 50: 0, 100: 0} # Added 5
        self.current_consecutive_makes = 0
        self.make_timestamps = []
        self.session_duration = 0
        self.fastest_21_makes = float('inf')
        self.most_makes_in_60_seconds = 0

    def load_and_process_data(self):
        with open(self.input_csv_path, 'r') as f:
            reader = self._csv_dict_reader(f) # Use a generator to handle potential file issues
            for row in reader:
                # Skip header row if it's mistakenly processed as a data row
                if row['current_frame_time'] == 'current_frame_time':
                    continue
                
                # Only process rows that represent a classified putt (not intermediate frames)
                if row['detailed_classification']:
                    self.putt_counter += 1
                    putt_index = self.putt_counter # Use sequential putt index
                    current_frame_time = float(row['current_frame_time']) # Get current_frame_time

                    self.putt_data.append({
                        'Putt Index': putt_index,
                        'Putt Classification': row['classification'],
                        'Putt Detailed Classification': row['detailed_classification'],
                        'Putt Time': current_frame_time # Store the time for each putt
                    })
                    self.total_putts += 1

                    if self.session_duration < current_frame_time:
                        self.session_duration = current_frame_time

                    classification = row['classification']
                    detailed_classification = row['detailed_classification']

                    if classification == "MAKE":
                        self.total_makes += 1
                        self.current_consecutive_makes += 1
                        self.make_timestamps.append(current_frame_time)
                        # Update makes by category
                        make_category = detailed_classification.replace("MAKE - ", "")
                        self.makes_by_category[make_category] = self.makes_by_category.get(make_category, 0) + 1
                    else: # MISS
                        self.total_misses += 1
                        self.max_consecutive_makes = max(self.max_consecutive_makes, self.current_consecutive_makes)
                        self.current_consecutive_makes = 0

                        # Update misses by category
                        if "CATCH" in detailed_classification:
                            self.misses_by_category["CATCH"] += 1
                        elif "TIMEOUT" in detailed_classification:
                            self.misses_by_category["TIMEOUT"] += 1
                        elif detailed_classification.startswith("MISS - RETURN:"): # More robust check for RETURN putts
                            self.misses_by_category["RETURN"] += 1
            
            # Final check for max consecutive makes after loop
            self.max_consecutive_makes = max(self.max_consecutive_makes, self.current_consecutive_makes)

            # Calculate consecutive makes counts
            temp_consecutive = 0
            for putt in self.putt_data:
                if putt['Putt Classification'] == "MAKE":
                    temp_consecutive += 1
                else:
                    for threshold in sorted(self.consecutive_makes_counts.keys()):
                        if temp_consecutive >= threshold:
                            self.consecutive_makes_counts[threshold] += 1
                    temp_consecutive = 0
            # After loop, check for any remaining consecutive makes
            for threshold in sorted(self.consecutive_makes_counts.keys()):
                if temp_consecutive >= threshold:
                    self.consecutive_makes_counts[threshold] += 1

            # Calculate Putts Per Minute and Makes Per Minute
            if self.total_putts > 0:
                self.make_percentage = (self.total_makes / self.total_putts) * 100
                self.miss_percentage = (self.total_misses / self.total_putts) * 100
            else:
                self.make_percentage = 0
                self.miss_percentage = 0

            if self.session_duration > 0:
                self.putts_per_minute = self.total_putts / (self.session_duration / 60)
                self.makes_per_minute = self.total_makes / (self.session_duration / 60)
            else:
                self.putts_per_minute = 0
                self.makes_per_minute = 0

            # Calculate Fastest 21 Makes
            if len(self.make_timestamps) >= 21:
                for i in range(len(self.make_timestamps) - 20):
                    time_diff = self.make_timestamps[i + 20] - self.make_timestamps[i]
                    if time_diff < self.fastest_21_makes:
                        self.fastest_21_makes = time_diff

            # Calculate Most Makes in 60 seconds
            if len(self.make_timestamps) > 0:
                for i in range(len(self.make_timestamps)):
                    count = 0
                    for j in range(i, len(self.make_timestamps)):
                        if self.make_timestamps[j] - self.make_timestamps[i] <= 60:
                            count += 1
                        else:
                            break
                    if count > self.most_makes_in_60_seconds:
                        self.most_makes_in_60_seconds = count

    def _csv_dict_reader(self, file_obj):
        """A robust CSV DictReader."""
        # Simple wrapper for now, can be expanded for more error handling
        import csv
        return csv.DictReader(file_obj)

    def generate_report(self, output_dir, player_info=None):
        """
        Generates session reports in both JSON and CSV format, and returns the data as a dict.
        The JSON is for application use, and the CSV is for human-readable downloads.
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Build the complete report data dictionary for JSON and in-app use
        report_data = {
            "session_info": {
                "player_name": player_info['name'] if player_info else "Unknown",
                "player_email": player_info['email'] if player_info else "Unknown",
                "report_generated_at": timestamp,
                "session_duration_seconds": round(self.session_duration, 2),
            },
            "analytic_stats": {
                "total_putts": self.total_putts,
                "total_makes": self.total_makes,
                "make_percentage": round(self.make_percentage, 2),
                "total_misses": self.total_misses,
                "miss_percentage": round(self.miss_percentage, 2),
                "makes_by_category": self.makes_by_category,
                "misses_by_category": self.misses_by_category,
            },
            "consecutive_stats": {
                "max_consecutive": self.max_consecutive_makes,
                "streaks_over_3": self.consecutive_makes_counts[3],
                "streaks_over_5": self.consecutive_makes_counts[5],
                "streaks_over_10": self.consecutive_makes_counts[10],
                "streaks_over_15": self.consecutive_makes_counts[15],
                "streaks_over_21": self.consecutive_makes_counts[21],
                "streaks_over_50": self.consecutive_makes_counts[50],
            },
            "time_stats": {
                "putts_per_minute": round(self.putts_per_minute, 2),
                "makes_per_minute": round(self.makes_per_minute, 2),
                "most_makes_in_60_seconds": self.most_makes_in_60_seconds,
                "fastest_21_makes_seconds": round(self.fastest_21_makes, 2) if self.fastest_21_makes != float('inf') else None,
            },
            "putt_list": self.putt_data
        }

        # 2. Generate JSON report
        json_report_filename = os.path.join(output_dir, f"session_report_{timestamp}.json")
        try:
            with open(json_report_filename, 'w') as f:
                json.dump(report_data, f, indent=4)
            print(f"JSON session report generated: {json_report_filename}")
        except IOError as e:
            print(f"Error writing JSON report: {e}")

        # 3. Generate CSV report
        self._generate_csv_report(output_dir, timestamp, player_info)

        # 4. Return data for in-app use
        return report_data

    def _generate_csv_report(self, output_dir, timestamp, player_info=None):
        """Generates a human-readable CSV summary of the session."""
        import csv
        csv_report_filename = os.path.join(output_dir, f"session_report_{timestamp}.csv")
        
        try:
            with open(csv_report_filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)

                writer.writerow(["Player Name", player_info['name'] if player_info else "Unknown"])
                writer.writerow(["Report Generated At", timestamp])
                writer.writerow([])

                writer.writerow(["Analytic Stats", ""])
                writer.writerow(["Total Putts", self.total_putts])
                writer.writerow(["Total Makes", self.total_makes])
                writer.writerow(["Make Percentage", f"{self.make_percentage:.2f}%"])
                writer.writerow(["Total Misses", self.total_misses])
                writer.writerow(["Miss Percentage", f"{self.miss_percentage:.2f}%"])
                writer.writerow([])

                writer.writerow(["Consecutive Stats", ""])
                writer.writerow(["Max Consecutive Makes", self.max_consecutive_makes])
                writer.writerow(["Streaks over 3", self.consecutive_makes_counts[3]])
                writer.writerow(["Streaks over 7", self.consecutive_makes_counts[7]])
                writer.writerow(["Streaks over 10", self.consecutive_makes_counts[10]])
                writer.writerow(["Streaks over 15", self.consecutive_makes_counts[15]])
                writer.writerow(["Streaks over 21", self.consecutive_makes_counts[21]])
                writer.writerow(["Streaks over 50", self.consecutive_makes_counts[50]])
                writer.writerow(["Streaks over 100", self.consecutive_makes_counts[100]]) # Assuming 100 is a key
                writer.writerow([])

                writer.writerow(["Time Stats", ""])
                writer.writerow(["Session Duration (seconds)", f"{self.session_duration:.2f}"])
                writer.writerow(["Putts Per Minute", f"{self.putts_per_minute:.2f}"])
                writer.writerow(["Makes Per Minute", f"{self.makes_per_minute:.2f}"])
                writer.writerow(["Most Makes in 60 seconds", self.most_makes_in_60_seconds])
                fastest_21_str = f"{self.fastest_21_makes:.2f}" if self.fastest_21_makes != float('inf') else "N/A"
                writer.writerow(["Fastest 21 Makes (seconds)", fastest_21_str])
                writer.writerow([])

                writer.writerow(["Putt History", ""])
                writer.writerow(["Putt Index", "Time (s)", "Classification", "Detailed Classification"])
                for putt in self.putt_data:
                    writer.writerow([putt['Putt Index'], f"{putt['Putt Time']:.2f}", putt['Putt Classification'], putt['Putt Detailed Classification']])
            print(f"CSV session report generated: {csv_report_filename}")
        except IOError as e:
            print(f"Error writing CSV report: {e}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate a session report from advanced evaluation results.")
    parser.add_argument("--input_csv", type=str, required=True, help="Path to the advanced_evaluation_results.csv file.")
    # Default output directory is now relative to the script's location
    default_output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Session.Reports")
    parser.add_argument("--output_dir", type=str, default=default_output_dir, help="Directory to save the session report.")
    args = parser.parse_args()

    reporter = SessionReporter(args.input_csv)
    reporter.load_and_process_data()
    reporter.generate_report(args.output_dir)
