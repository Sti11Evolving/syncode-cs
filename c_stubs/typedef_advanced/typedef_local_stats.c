double average_even_value(const int values[], int length);

int main(void)
{
    int values[] = {3, 8, 4, 7, 10};
    double average;

    average = average_even_value(values, 5);

    return 0;
}

// Define and use a local typedef struct named EvenStats with a long total
// and an int count. Return 0.0 if there are no even values.
double average_even_value(const int values[], int length)
{
