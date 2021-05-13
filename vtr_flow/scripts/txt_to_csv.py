import argparse

csv_parser = argparse.ArgumentParser(
    description="Convert a tab deliniated text file to a comma deliniated csv file."
)
csv_parser.add_argument("txt_file", help="The text file to be parsed")
args = csv_parser.parse_args()

with open(args.txt_file) as file:
    with open("results.csv", "w+") as target:
        for line in file:
            data = line.split("\t")
            for column in data:
                if column == "\n":
                    target.write(column)
                else:
                    target.write(column + ",")
