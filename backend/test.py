import os
import sys
import re

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

os.environ['JAVA_HOME'] = r"C:\Program Files\Java\jdk-17.0.19"

from pyspark.sql import SparkSession
from pyspark.sql.functions import col
spark = SparkSession.builder \
    .appName("BasicPySparkTest") \
    .master("local[*]") \
    .getOrCreate()

# Sample data
data = [
    (1, "Alice", 25),
    (2, "Bob", 30),
    (3, "Charlie", 35)
]

# Column names
columns = ["id", "name", "age"]

# Create DataFrame
df = spark.createDataFrame(data, columns)

# Show DataFrame
print("Original DataFrame:")
df.show()

# Filter data
filtered_df = df.filter(col("age") > 28)

print("Filtered DataFrame (age > 28):")
filtered_df.show()

# Print schema
print("Schema:")
df.printSchema()

# Stop Spark session
spark.stop()