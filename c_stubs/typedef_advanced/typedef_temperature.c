typedef double Temperature;
typedef Temperature Celsius;
typedef double Kelvin;

Celsius kelvin_to_celsius(Kelvin temperature);

int main(void)
{
    Kelvin start = 300.0;
    Celsius result;

    result = kelvin_to_celsius(start);

    return 0;
}

// Convert Kelvin to Celsius.
Celsius kelvin_to_celsius(Kelvin temperature)
{
